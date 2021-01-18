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
    )

    @classmethod
    def config_key(cls, datasource, context):
        # Collect only once per device
        log.info('In config_key {} {} {} {}'.format(context.device().id,
                                                    datasource.getCycleTime(context),
                                                    datasource.plugin_classname,
                                                    'Vault'))

        return (context.device().id,
                datasource.getCycleTime(context),
                'Vault'
                )

    @classmethod
    def params(cls, datasource, context):
        return {}

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @staticmethod
    def get_code(response, instance):
        log.debug('AAA - get_code response: {}'.format(response))
        log.debug('AAA - get_code instance: {}'.format(instance))
        d = dict(instance=instance,
                 code=response.code,
                 error=False,
                 response=response)
        return d

    @staticmethod
    def err_test(response, instance):
        # log.debug('XXX - err_test response: {}'.format(response))
        # log.debug('XXX - err_test response2: {}'.format(response.value))
        # log.debug('XXX - err_test instance: {}'.format(instance))
        d = dict(instance=instance,
                 message=response.value,
                 error=True,
                 response=response)
        # log.debug('XXX - err_test d: {}'.format(d))
        return d

    @staticmethod
    @inlineCallbacks
    def get_body(result):
        log.debug('AAA - get_body result: {}'.format(result))
        log.debug('AAA - get_body error: {}'.format(result['error']))
        if result['error']:
            returnValue(result)
        # result['body'] = readBody(result['response'])
        body = readBody(result['response'])
        result['body'] = yield body
        returnValue(result)


    def collect(self, config):
        log.debug('Starting Vault collect')

        # TODO: test with a non-responding instance

        ds0 = config.datasources[0]
        log.debug('AAA - collect config: {}'.format(config))
        log.debug('AAA - collect ds: {}'.format(config.datasources))
        log.debug('AAA - collect instances: {}'.format(ds0.zVaultInstances))

        agent = Agent(reactor, contextFactory=SkipCertifContextFactory())
        headers = {
            "Accept": ['application/json'],
        }

        deferreds = []

        for instance in ds0.zVaultInstances:
            log.debug('AAA - collect instance: {}'.format(instance))
            url = 'https://{}:{}/v1/sys/health'.format(instance, ds0.zVaultPort)
            log.debug('AAA - collect url: {}'.format(url))
            try:
                # response = agent.request('GET', url, Headers(headers))
                d = agent.request('GET', url, Headers(headers))
                # d.addCallback(readBody)
                # d.addCallback(self.add_tag, instance).addCallback(self.get_code, instance).addCallback(self.get_body)
                # TODO: callbacks for errors
                # d.addCallback(self.get_code, instance).addCallback(self.get_body)
                d.addCallback(self.get_code, instance)
                d.addErrback(self.err_test, instance)
                d.addCallback(self.get_body)

                # response_body = yield readBody(response)
                # response_body = json.loads(response_body)
                # returnValue(response_body)
                deferreds.append(d)
            except Exception as e:
                log.exception('{}: failed to get data for {}'.format(config.id, ds0))
                log.exception('{}: Exception: {}'.format(config.id, e))
        # returnValue()
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
        for r in result:
            log.debug('onSuccess r: {}'.format(r))
            '''
            instance, response = r[1]
            log.debug('onSuccess instance: {}'.format(instance))
            log.debug('onSuccess code: {}'.format(response.code))
            log.debug('onSuccess body: {}'.format(readBody(response)))
            '''
            if not r[0]:
                continue
            instance_data = r[1]
            instance = instance_data['instance']
            component = prepId('vaultinstance_{}'.format(instance))
            if instance_data['error']:
                data['values'][component]['active'] = 0
                # Retrieve cluster
                log.debug('onSuccess config: {}'.format(config.datasources))
                for ds in config.datasources:
                    log.debug('onSuccess ds: {}'.format(ds.component))
                    log.debug('onSuccess ds: {}'.format(ds.component == component))
                    log.debug('onSuccess ds: {}'.format(ds.cluster_name))
                    if ds.component == component:
                        cluster = ds.cluster_name
                        break
                # Update cluster metrics
                if cluster not in cluster_metrics:
                    cluster_metrics[cluster] = {'num_sealed': 0, 'num_active': 0, 'num_unavailable': 0}
                    cluster_messages[cluster] = {'unavailable': [], 'sealed': []}
                cluster_metrics[cluster]['num_unavailable'] = cluster_metrics[cluster]['num_unavailable'] + 1
                data['values'][component]['active'] = 0     # Unknown
                # Add instance to list of unavail instances
                cluster_messages[cluster]['unavailable'].append(instance)
            else:
                health = json.loads(instance_data['body'])
                cluster = health['cluster_name']
                if cluster not in cluster_metrics:
                    cluster_metrics[cluster] = {'num_sealed': 0, 'num_active': 0, 'num_unavailable': 0}
                    cluster_messages[cluster] = {'unavailable': [], 'sealed': []}
                sealed = 1 if health['sealed'] else 0
                if sealed:
                    cluster_messages[cluster]['sealed'].append(instance)
                active = 1 if health['standby'] else 2
                cluster_metrics[cluster]['num_sealed'] = cluster_metrics[cluster]['num_sealed'] + sealed
                cluster_metrics[cluster]['num_active'] = cluster_metrics[cluster]['num_active'] + max(active, 1)
                data['values'][component]['sealed'] = sealed
                data['values'][component]['init'] = 1 if health['initialized'] else 0
                data['values'][component]['active'] = active


        log.debug('onSuccess cluster_metrics: {}'.format(cluster_metrics))
        for cluster, metrics in cluster_metrics.items():
            component = prepId('vaultcluster_{}'.format(cluster))
            data['values'][component]['num_sealed'] = metrics['num_sealed']
            data['values'][component]['num_active'] = metrics['num_active']
            data['values'][component]['num_unavailable'] = metrics['num_unavailable']

        '''
        data['events'].append({
            'device': config.id,
            'component': comp_id,
            'severity': status_value,
            'eventKey': 'ConnectorStatus',
            'eventClassKey': 'ConnectorStatus',
            'summary': 'Connector {} - Status is {}'.format(comp_title, connector_metrics['status']),
            'message': 'Connector {} - Status is {}'.format(comp_title, connector_metrics['status']),
            'eventClass': '/Status/Scality/Connector',
        })
        '''

        return data

    def onError(self, result, config):
        log.error('XXX Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
