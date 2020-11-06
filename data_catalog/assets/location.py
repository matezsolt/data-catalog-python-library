from data_catalog.client.models.location import Location as ClientLocation


class Location (ClientLocation):
    def __init__(self, type=None, parameters=None):
        super().__init__(type=type, parameters=parameters)

    def get_parameter(self, key):
        values = [parameter.value for parameter in self.parameters if parameter.key == key]

        return values[0] if len(values) > 0 else None
