# stdlib Imports
import json
import base64

# Twisted Imports
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import Agent, readBody, BrowserLikePolicyForHTTPS
from twisted.internet import reactor, ssl
from twisted.web.http_headers import Headers
from twisted.web.iweb import IPolicyForHTTPS

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from zope.interface import implementer


@implementer(IPolicyForHTTPS)
class SkipCertifContextFactory(object):
    def __init__(self):
        self.default_policy = BrowserLikePolicyForHTTPS()

    def creatorForNetloc(self, hostname, port):
        return ssl.CertificateOptions(verify=False)

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

        # basicAuth = base64.encodestring('{}:{}'.format(zScalityUsername, zScalityPassword))
        # authHeader = "Basic " + basicAuth.strip()
        # scheme = 'https' if zScalityUseSSL else 'http'

        results = {}
        agent = Agent(reactor, contextFactory=SkipCertifContextFactory())
        headers = {
                   "Accept": ['application/json'],
                   }

        # Supervisor only
        try:
            url = 'https://{}:{}/v1/sys/health'.format(device.id, zVaultPort)
            response = yield agent.request('GET', url, Headers(headers))
            # TODO: gather http code
            response_body = yield readBody(response)
            response_body = json.loads(response_body)
            results['cluster'] = response_body
        except Exception, e:
            log.error('%s: %s', device.id, e)
            returnValue(None)

        for instance in zVaultInstances:
            log.debug('*** instance: {}'.format(instance))
            try:
                url = 'https://{}:{}/v1/sys/health'.format(instance, zVaultPort)
                response = yield agent.request('GET', url, Headers(headers))
                # TODO: gather http code
                response_body = yield readBody(response)
                response_body = json.loads(response_body)
                results[instance] = response_body
            except Exception, e:
                log.error('%s: %s', device.id, e)
                results[instance] = {'error': e}
                # returnValue(None)

        '''
        for item, base_url in queries.items():
            try:
                data = []
                offset = 0
                limit = 20
                while True:
                    url = base_url.format(scheme, device.id, offset, limit)
                    response = yield agent.request('GET', url, Headers(headers))
                    response_body = yield readBody(response)
                    response_body = json.loads(response_body)
                    data.extend(response_body['_items'])
                    offset += limit
                    if len(data) >= response_body['_meta']['count'] or offset > response_body['_meta']['count']:
                        break
                results[item] = data
            except Exception, e:
                log.error('%s: %s', device.id, e)
                returnValue(None)
        '''

        returnValue(results)

    def process(self, device, results, log):
        log.debug('results: {}'.format(results))

        rm = []

        clusternames = set()
        log.debug('clusternames: {}'.format(clusternames))
        for instance, result in results.items():
            log.debug('instance: {}'.format(instance))
            clustername =  result.get("cluster_name")
            if clustername:
                clusternames.add(clustername)
            log.debug('clusternames: {}'.format(clusternames))

        log.debug('clusternames: {}'.format(clusternames))

        for cluster in clusternames:
            log.debug('cluster: {}'.format(cluster))
            if not cluster:
                continue
            om_cluster = ObjectMap()
            om_cluster.id = self.prepId('vaultcluster_{}'.format(cluster))
            om_cluster.title = cluster
            clusterpath = 'vaultClusters/vaultcluster_{}'.format(self.prepId(clustername))
            rm.append(RelationshipMap(compname='',
                                      relname='vaultClusters',
                                      modname='ZenPacks.community.Vault.VaultCluster',
                                      objmaps=[om_cluster]))

            vault_instances = []
            for instance, data in results.items():
                log.debug('instance: {}'.format(instance))
                if instance == 'cluster' or 'cluster_name' not in data:
                    continue
                clustername = data['cluster_name']
                if clustername != cluster:
                    continue
                om_instance = ObjectMap()
                om_instance.id = self.prepId('vaultinstance_{}'.format(instance))
                om_instance.title = instance
                om_instance.cluster_name = data['cluster_name']
                om_instance.version = data['version']
                om_instance.replication_performance_mode = data['replication_performance_mode']
                om_instance.performance_standby = data['performance_standby']
                om_instance.replication_dr_mode = data['replication_dr_mode']
                # TODO: set values to integer, not booleans
                # om_instance.sealed = data['sealed']
                # om_instance.initialized = data['initialized']
                # om_instance.standby = data['standby']
                vault_instances.append(om_instance)

            om_instance = ObjectMap()
            instance = 'st-vault-l06.staging.credoc.be'
            om_instance.id = self.prepId('vaultinstance_{}'.format(instance))
            om_instance.title = instance
            om_instance.cluster_name = 'vault-cluster-e414faa8'
            vault_instances.append(om_instance)

            log.debug('vault_instances: {}'.format(vault_instances))
            for i in vault_instances:
                log.debug('vault_instance: {}'.format(i))
            rm.append(RelationshipMap(compname=clusterpath,
                                      relname='vaultInstances',
                                      modname='ZenPacks.community.Vault.VaultInstance',
                                      objmaps=vault_instances))

        log.debug('rm: {}'.format(rm))
        return rm

