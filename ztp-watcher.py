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
from nornir.plugins.tasks.networking import netmiko_send_command


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
        logging.basicConfig(format='\n%(asctime)s %(message)s',
                            datefmt='%m/%d/%Y %I:%M:%S %p',
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
        result = nr.run(
            task=netmiko_send_command,
            command_string=f'copy tftp://{tftpaddr}/{imgfile} flash:',
            delay_factor=6,
        )
        std_log(result)

    def on_created(self, event):

        if event.is_directory:
            return None

        else:
            newfile = event.src_path.rpartition('/')[2]
            if not any(str in newfile for str in ignorefiles):
                Logger(f'File created: {newfile}')
                hostname = newfile.split('_')[0]
                hostaddr = newfile.split('_')[1]
                Logger(f'Transferring file to {hostname} (IP: {hostaddr}).')
                x = threading.Thread(target=self.os_upgrade, args=(
                    hostname, hostaddr, tftpaddr, imgfile))
                x.start()


if __name__ == '__main__':
    w = Watcher()
    w.run()
