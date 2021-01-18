import json

from . import schema


class VaultCluster(schema.VaultCluster):

    def get_unavailable_nodes(self):
        return self.unavailable_nodes

    def get_sealed_nodes(self):
        return self.sealed_nodes

