#!/usr/bin/python3
# Author: DS, Synergy Information Solutions, Inc.


import time
import os
import threading
import logging
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from nornir import InitNornir
from nornir.plugins.tasks.networking import netmiko_send_command, netmiko_send_config


with open('./ztpconfig.yaml', 'r') as f:
    config = yaml.safe_load(f)

logfile = config['logfile']
watch_dir = config['watch_dir']
tftpaddr = config['tftpaddr']
imgfile = config['imgfile']
username = config['username']
password = config['password']

ignorefiles = ['.swp', '.save']


def std_log(agg_result):
    for k, multi_result in agg_result.items():
        for result_obj in multi_result:
            Logger(f'{k}\n{result_obj.result}')


class Logger:

    def __init__(self, logdata):
        logging.basicConfig(format='%(asctime)s %(message)s',
                            datefmt='%Y/%m/%d %I:%M:%S %p',
                            filename=logfile,
                            level=logging.INFO)
        logging.info(f'-- {logdata}')


class Watcher:

    def __init__(self):
        self.observer = Observer()

    def run(self):
        event_handler = Handler()
        self.observer.schedule(event_handler, watch_dir, recursive=False)
        self.observer.start()
        Logger('Starting FreeZTP Provisioning Watcher.')
        try:
            while True:
                time.sleep(5)

        except KeyboardInterrupt:
            self.observer.stop()
            print('\nKeyboard interrupt.')
            Logger('Stopping FreeZTP Provisioning Watcher (Keyboard interrupt).')

        except:
            self.observer.stop()
            print('Error.')
            Logger('Error.\n')


class Handler(FileSystemEventHandler):

    def os_upgrade(self, hostname, hostaddr, tftpaddr, imgfile):

        time.sleep(45)
        Logger(f'{hostname} starting TFTP image transfer.')

        nr = InitNornir(
            inventory={
                'options': {
                    'hosts': {
                        hostname: {
                            'hostname': hostaddr,
                            'username': username,
                            'password': password,
                            'platform': 'ios'
                        }
                    }
                }
            }
        )
        copyfile = nr.run(
            task=netmiko_send_command,
            command_string=f'copy tftp://{tftpaddr}/{imgfile} flash:',
            delay_factor=6,
        )
        std_log(copyfile)
        Logger(f'{hostname} TFTP transfer completed, setting boot variable.')

        bootcmds = f'default boot sys\nboot system flash:{imgfile}'
        bootcmds_list = bootcmds.splitlines()
        bootvar = nr.run(
            task=netmiko_send_config,
            config_commands=bootcmds_list
        )
        std_log(bootvar)
        Logger(f'{hostname} boot variable has been set, writing config.')

        writemem = nr.run(
            task=netmiko_send_command,
            command_string='write mem',
        )
        std_log(writemem)
        Logger(f'{hostname} config written, ready to reload/power off.')

    def on_created(self, event):

        if event.is_directory:
            return None

        else:
            newfile = event.src_path.rpartition('/')[2]
            if not any(str in newfile for str in ignorefiles):
                Logger(f'File created: {newfile}')
                hostname = newfile.split('_')[0]
                hostaddr = newfile.split('_')[1]
                Logger(
                    f'Waiting 45 seconds for TFTP image transfer to {hostname} (IP: {hostaddr}).')
                x = threading.Thread(target=self.os_upgrade, args=(
                    hostname, hostaddr, tftpaddr, imgfile))
                x.start()


if __name__ == '__main__':
    w = Watcher()
    w.run()
