# stdlib Imports
import json

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from ZenPacks.community.Vault.lib.utils import SkipCertifContextFactory

# Twisted Imports
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers


class vault(PythonPlugin):

    requiredProperties = (
        'zVaultPort',
        'zVaultInstances',
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties

    @inlineCallbacks
    def collect(self, device, log):
        """Asynchronously collect data from device. Return a deferred/"""
        log.info('%s: collecting data', device.id)

        zVaultPort = getattr(device, 'zVaultPort', None)
        zVaultInstances = getattr(device, 'zVaultInstances', None)

        results = {}
        agent = Agent(reactor, contextFactory=SkipCertifContextFactory())
        headers = {
                   "Accept": ['application/json'],
                   }

        for instance in zVaultInstances:
            try:
                url = 'https://{}:{}/v1/sys/health'.format(instance, zVaultPort)
                response = yield agent.request('GET', url, Headers(headers))
                response_body = yield readBody(response)
                response_body = json.loads(response_body)
                results[instance] = response_body
            except Exception, e:
                log.error('%s: %s', device.id, e)
                results[instance] = {'error': e}

        returnValue(results)

    def process(self, device, results, log):
        log.debug('results: {}'.format(results))

        # Collect cluster data
        rm = []
        clusternames = {}
        for instance, result in results.items():
            clustername =  result.get("cluster_name")
            if clustername and clustername not in clusternames:
                clusternames[clustername] = result.get("cluster_id")
        # In most cases, there will be one single cluster
        # e.g. : {u'vault-cluster-e414fxxx': u'49898bd6-09fb-xxxx-xxxx-a8fc9c738d99'}

        for cluster, clusterid in clusternames.items():
            if not cluster:
                continue
            # Map vault clusters
            om_cluster = ObjectMap()
            om_cluster.id = self.prepId('vaultcluster_{}'.format(cluster))
            om_cluster.title = cluster
            om_cluster.cluster_name = cluster
            om_cluster.cluster_id = clusterid
            clusterpath = 'vaultClusters/vaultcluster_{}'.format(self.prepId(cluster))
            rm.append(RelationshipMap(compname='',
                                      relname='vaultClusters',
                                      modname='ZenPacks.community.Vault.VaultCluster',
                                      objmaps=[om_cluster]))

            # Map vault instances
            vault_instances = []
            for instance, data in results.items():
                if instance == 'cluster' or 'cluster_name' not in data:
                    continue
                clustername = data['cluster_name']
                if clustername != cluster:
                    continue
                om_instance = ObjectMap()
                om_instance.id = self.prepId('vc_{}_vaultinstance_{}'.format(cluster, instance))
                om_instance.title = '{} ({})'.format(instance, cluster)
                om_instance.cluster_name = data['cluster_name']
                om_instance.host = instance
                om_instance.version = data['version']
                om_instance.replication_performance_mode = data['replication_performance_mode']
                om_instance.performance_standby = data['performance_standby']
                om_instance.replication_dr_mode = data['replication_dr_mode']
                vault_instances.append(om_instance)
            rm.append(RelationshipMap(compname=clusterpath,
                                      relname='vaultInstances',
                                      modname='ZenPacks.community.Vault.VaultInstance',
                                      objmaps=vault_instances))
        return rm

