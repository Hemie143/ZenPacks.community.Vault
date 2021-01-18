import json
import logging
import base64

# Twisted Imports
from twisted.internet import reactor, ssl
from twisted.internet.defer import returnValue, inlineCallbacks, DeferredList
from twisted.web.client import Agent, readBody, BrowserLikePolicyForHTTPS
from twisted.web.http_headers import Headers
from twisted.web.iweb import IPolicyForHTTPS

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin
from zope.interface import implementer
from Products.ZenUtils.Utils import prepId
from Products.DataCollector.plugins.DataMaps import ObjectMap


# Setup logging
log = logging.getLogger('zen.Vault')

# TODO: Move this factory in a library
@implementer(IPolicyForHTTPS)
class SkipCertifContextFactory(object):
    def __init__(self):
        self.default_policy = BrowserLikePolicyForHTTPS()

    def creatorForNetloc(self, hostname, port):
        return ssl.CertificateOptions(verify=False)


class Vault(PythonDataSourcePlugin):
    proxy_attributes = (
        'zVaultPort',
        'zVaultInstances',
        'cluster_name',
        'host'
    )

    @classmethod
    def config_key(cls, datasource, context):
        # Collect only once per device
        log.info('In config_key {} {} {}'.format(context.device().id,
                                                    datasource.getCycleTime(context),
                                                    datasource.plugin_classname,
                                                    ))

        return (context.device().id,
                datasource.getCycleTime(context),
                datasource.plugin_classname,
                )

    @classmethod
    def params(cls, datasource, context):
        return {}

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @staticmethod
    def get_code(response, instance):
        d = dict(instance=instance,
                 code=response.code,
                 error=False,
                 response=response)
        return d

    @staticmethod
    def err_test(response, instance):
        d = dict(instance=instance,
                 message=response.value,
                 error=True,
                 response=response)
        return d

    @staticmethod
    @inlineCallbacks
    def get_body(result):
        if result['error']:
            returnValue(result)
        body = readBody(result['response'])
        result['body'] = yield body
        returnValue(result)


    def collect(self, config):
        log.debug('Starting Vault collect')

        ds0 = config.datasources[0]
        agent = Agent(reactor, contextFactory=SkipCertifContextFactory())
        headers = {
            "Accept": ['application/json'],
        }

        deferreds = []
        for ds in config.datasources:
            if ds.template != 'VaultInstance':
                continue
            url = 'https://{}:{}/v1/sys/health'.format(ds.host, ds.zVaultPort)
            try:
                d = agent.request('GET', url, Headers(headers))
                d.addCallback(self.get_code, ds.host)
                d.addErrback(self.err_test, ds.host)
                d.addCallback(self.get_body)
                deferreds.append(d)
            except Exception as e:
                log.exception('{}: failed to get data for {}'.format(config.id, ds0))
                log.exception('{}: Exception: {}'.format(config.id, e))
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('Success job - result is {}'.format(result))
        data = self.new_data()

        # Default status codes
        # 200 = initialized, unsealed and active
        # 429 = unsealed and standby
        # 472 = disaster recovery mode replication secondary and active
        # 473 = performance standby
        # 501 = not initialized
        # 503 = sealed

        cluster_metrics = {}
        cluster_messages = {}

        # Retrieve clusternames from components (datasources)
        clusters = set()
        for ds in config.datasources:
            if ds.cluster_name:
                clusters.add(ds.cluster_name)

        # Pre-fill the cluster data (metrics and messages
        for cluster in clusters:
            cluster_metrics[cluster] = {'num_sealed': 0, 'num_active': 0, 'num_unavailable': 0}
            cluster_messages[cluster] = {'unavailable': [], 'sealed': []}

        # Parse the results
        for r in result:
            if not r[0]:
                continue
            instance_data = r[1]
            instance = instance_data['instance']
            component = prepId('vaultinstance_{}'.format(instance))
            if instance_data['error']:
                # In case of error, no connection ? unavailable ?
                data['values'][component]['active'] = 0
                # Retrieve cluster
                for ds in config.datasources:
                    if ds.component == component:
                        cluster = ds.cluster_name
                        break
                # Update cluster metrics
                cluster_metrics[cluster]['num_unavailable'] = cluster_metrics[cluster]['num_unavailable'] + 1
                data['values'][component]['active'] = 0     # Unknown
                # Add instance to list of unavail instances
                cluster_messages[cluster]['unavailable'].append(instance)
            else:
                # A JSON object is available
                health = json.loads(instance_data['body'])
                cluster = health['cluster_name']
                sealed = 1 if health['sealed'] else 0
                if sealed:
                    cluster_messages[cluster]['sealed'].append(instance)
                active = 1 if health['standby'] else 2      # active: 0=unknown, 1=standby, 2=active
                cluster_metrics[cluster]['num_sealed'] = cluster_metrics[cluster]['num_sealed'] + sealed
                cluster_metrics[cluster]['num_active'] = cluster_metrics[cluster]['num_active'] + active - 1
                data['values'][component]['sealed'] = sealed
                data['values'][component]['init'] = 1 if health['initialized'] else 0
                data['values'][component]['active'] = active

        # Fill in the cluster metrics
        for cluster, metrics in cluster_metrics.items():
            component = prepId('vaultcluster_{}'.format(cluster))
            data['values'][component]['num_sealed'] = metrics['num_sealed']
            data['values'][component]['num_active'] = metrics['num_active']
            data['values'][component]['num_unavailable'] = metrics['num_unavailable']

        # Fill in the attributes of clusters with unavailable and sealed nodes
        for cluster, cdata in cluster_messages.items():
            data['maps'].append(
                ObjectMap({
                    'relname': 'vaultClusters',
                    'modname': 'ZenPacks.community.Vault.VaultCluster',
                    'id': prepId('vaultcluster_{}'.format(cluster)),
                    'unavailable_nodes': cdata['unavailable'],
                    'sealed_nodes': cdata['sealed'],
                })
            )
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
