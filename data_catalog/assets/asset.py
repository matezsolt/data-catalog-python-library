from csv import Sniffer
from io import BytesIO
from typing import Union, List, Dict
from urllib.request import urlopen

import pandas as pd
from datetime import datetime

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContainerClient

from data_catalog.client.asset import AssetResponse
from data_catalog.assets.version import Version
from data_catalog.assets.version_service import VersionService
from data_catalog.assets import Location


class Asset(AssetResponse):
    """
    A service level class to extend the AssetResponse class generated by OpenAPI.
    It provides methods to obtain data from an Asset
    """

    version_service: VersionService

    def __init__(self, id=None, created_at=None, updated_at=None, name=None, description=None, short_description=None,
                 location=None, tags=None, format=None, namespace=None, local_vars_configuration=None):
        """
        Constructor of Asset
        :param str id:
        :param str created_at:
        :param str updated_at:
        :param str name:
        :param str description:
        :param str short_description:
        :param Location location: The location where the asset data can be found
        :param list[str] tags: list of tags
        :param str format:
        :param str namespace:
        :param local_vars_configuration:
        """

        super().__init__(id=id, created_at=created_at, updated_at=updated_at, name=name, description=description,
                         short_description=short_description, location=location, tags=tags, format=format, namespace=namespace,
                         local_vars_configuration=local_vars_configuration)

        if self.location is not None:
            self.location = Location(location.type, location.parameters)

        self.version_service = VersionService()

    @staticmethod
    def from_response(asset_response: AssetResponse):
        """
        Converts an AssetResponse to a Response
        :param AssetResponse asset_response: Asset client generated with OpenAPI
        :return: asset
        :rtype: Asset
        """
        asset_response.__class__ = Asset
        if asset_response.location is not None:
            asset_response.location = Location(asset_response.location.type, asset_response.location.parameters)

        return asset_response

    # TODO: get data from a certain version
    def get_data(self, version_name: str = None) -> pd.DataFrame:
        """
        Obtains data from its location and returns it in Pandas Data Frame.
        Version is only supported when the location type is azureblob.
        :param str version_name: the name of the version to download. If none, the latest version will be downloaded.
        :return: if location type is 'url', then Pandas Data Frame,
                 if it  is 'azureblob', then ContainerClient
        :rtype: Union[pd.DataFrame, ContainerClient]
        """

        if self.location is None:
            raise ValueError('Asset location is not defined')

        # check location type
        if self.location.type == 'url':
            return self._get_data_from_url()
        elif self.location.type == 'azureblob':
            return self._get_data_from_container(version_name=version_name)
        else:
            raise NotImplementedError

    def _get_data_from_url(self) -> pd.DataFrame:
        """
        Obtains data when the location type is url
        :return: Pandas DataFrame
        :rtype: pd.DataFrame
        """
        url = self.location.get_parameter('url')
        if url is None:
            raise ValueError('Location has no url parameter')

        try:
            if self.format == 'csv':
                with urlopen(url) as f:
                    stream = BytesIO(f.read())

                stream.seek(0)
                delimiter = Sniffer().sniff(stream.read().decode()).delimiter

                stream.seek(0)
                data_frame = pd.read_csv(stream, sep=delimiter)
            elif self.format == 'json':
                data_frame = pd.read_json(url)
            else:
                raise NotImplementedError
        except pd.errors.ParserError:
            raise ValueError('Could not parse data from url')

        return data_frame

    def _get_data_from_container(self, version_name: str = None) -> pd.DataFrame:
        """
        Obtains data when the location type is azureblob (data from Azure Blob Storage)
        :return: pandas dataframe
        :rtype: pd.DataFrame
        """
        container = self._get_container()
        if version_name is None:
            blob_list = container.list_blobs()
        else:
            version = self.get_version(version=version_name)
            blob_list = []

            for content in version.contents:
                try:
                    blob = container.get_blob_client(content.name)
                    if blob.get_blob_properties().last_modified > content.last_modified:
                        raise FileNotFoundError
                except (ResourceNotFoundError, FileNotFoundError):
                    raise FileNotFoundError('The blob %s was not found, or it was modified.' % content.name)

                blob_list.append(blob)

        data_frames = []
        try:
            if self.format == 'csv':
                for blob in blob_list:
                    stream = BytesIO()
                    container.download_blob(blob).readinto(stream)

                    stream.seek(0)
                    delimiter = Sniffer().sniff(stream.read().decode()).delimiter

                    stream.seek(0)
                    data_frames.append(pd.read_csv(stream, sep=delimiter))
            elif self.format == 'json':
                for blob in blob_list:
                    stream = BytesIO()
                    container.download_blob(blob).readinto(stream)

                    stream.seek(0)
                    data_frames.append(pd.read_json(stream))
            else:
                raise NotImplementedError
        except pd.errors.ParserError:
            raise ValueError('Could not parse the data from the blob container')

        return pd.concat(data_frames, ignore_index=True)

    def _get_container(self) -> ContainerClient:
        """

        :return:
        """
        account_url = self.location.get_parameter('accountUrl')
        container_name = self.location.get_parameter('containerName')
        credential = None

        if self.location.get_parameter('sasToken') is not None:
            expiry_time = datetime \
                .strptime(self.location.get_parameter('expiryTime'), '%Y-%m-%dT%H:%M:%SZ')

            if expiry_time >= datetime.now():
                credential = self.location.get_parameter('sasToken')

        if credential is None:
            credential = self.location.get_parameter('accountKey')

        if None in [account_url, container_name, credential]:
            raise ValueError('Parameters missing to create the container.')

        return ContainerClient(account_url=account_url,
                               container_name=container_name,
                               credential=credential)

    def get_version(self, version: str) -> Version:
        """
        Get version details of an asset by its name.
        :param str version: the name of the version
        :return: the requested version details
        :rtype: Version
        """
        return self.version_service.get_version(asset_id=self.id, name=version)

    def list_versions(self, output_format: str = 'list') -> Union[List[Version], Dict[str, Version], pd.DataFrame]:
        """
        Lists all versions of an asset by calling the function with the same name from VersionService.
        :param output_format: The format in which the data will be listed.
        :return: All versions available.
                 If the output_format is 'list': returns a list of versions.
                 If the output_format is 'dict': returns a mapping from id to version as a dictionary.
                 If the output_format is 'dataframe': returns a pandas DataFrame, where each row represents a version,
                                                      the indexes are the ids, and the columns represent the attributes
                                                      of the version.
        """
        return self.version_service.list_versions(asset_id=self.id, output_format=output_format)

    def create_version(self):
        """
        Create a new version of an asset's current state by calling the function with the same name from VersionService
        :return:
        """
        self.version_service.create_version(asset_id=self.id)

    def delete_version(self, version: str):
        """
        Delete a version of an asset by its name by calling the function with the same name form VersionService
        :param version: the name of the version to delete
        :return:
        """
        self.version_service.delete_version(asset_id=self.id, version=version)
