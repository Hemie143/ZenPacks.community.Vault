# from . import schema
import os
import logging
log = logging.getLogger('zen.Vault')

from ZenPacks.zenoss.ZenPackLib import zenpacklib
zenpacklib.load_yaml()

CFG = zenpacklib.load_yaml([os.path.join(os.path.dirname(__file__), "zenpack.yaml")], verbose=False, level=30)
schema = CFG.zenpack_module.schema

VAULT_PLUGINS = [
    'community.json.vault'
]
DEVICE_CLASS = '/Server/SSH/Linux/Vault'


class ZenPack(schema.ZenPack):
    def install(self, app):
        self._update_plugins(DEVICE_CLASS)
        # Call super last to perform the rest of the installation
        super(ZenPack, self).install(app)

    def _update_plugins(self, organizer):
        # TODO: Add modeler plugin
        log.info('Update plugins list for Vault organizer')
        try:
            # Vault device class
            vault_dc = self.dmd.Devices.getOrganizer(organizer)
        except Exception:
            # Device class doesn't exist.
            pass
        else:
            # Our ZenPack's Modeler Plugins
            # myPlugins = ['aalvarez.snmp.HardDisk', 'aalvarez.snmp.RaidCard']
            # log.debug('Update plugins list for NovaHost organizer')
            # self.device_classes[organizer].zProperties['zCollectorPlugins'] = NOVAHOST_PLUGINS

            # Append Plugins to NovaHost's existing plugins
            # log.info('Correcting plugins list for Vault organizer')
            zCollectorPlugins = list(vault_dc.zCollectorPlugins) + VAULT_PLUGINS
            # log.info('zCollectorPlugins1: {}'.format(zCollectorPlugins))
            # Assign to the device class
            self.device_classes[DEVICE_CLASS].zProperties['zCollectorPlugins'] = zCollectorPlugins
            log.info('zCollectorPlugins1: {}'.format(self.device_classes[DEVICE_CLASS].zProperties['zCollectorPlugins']))

        '''
        log.debug('Update plugins list for Vault organizer')
        self.device_classes[organizer].zProperties['zCollectorPlugins'] = VAULT_PLUGINS
        try:
            plugins = self.dmd.Devices.getOrganizer('/Server/SSH/Linux').zCollectorPlugins
            self.device_classes[organizer].zProperties['zCollectorPlugins'] += plugins
        except KeyError:
            log.debug("'Server/SSH/Linux' organizer does not exist")
        '''
