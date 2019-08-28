#!/usr/bin/python3
# Author: DS, Synergy Information Solutions, Inc.


import time
import os
import threading
import logging
import yaml
import socket
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from nornir import InitNornir
from nornir.plugins.tasks.networking import netmiko_send_command, netmiko_send_config


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
        Logger('Starting ZTP Provisioning Watcher.')
        try:
            while True:
                time.sleep(5)

        except KeyboardInterrupt:
            self.observer.stop()
            print('\nKeyboard interrupt.')
            Logger('Stopping ZTP Provisioning Watcher (Keyboard interrupt).')

        except:
            self.observer.stop()
            print('Error.')
            Logger('Error.\n')


class Handler(FileSystemEventHandler):

    def on_created(self, event):

        ignorefiles = ['.swp', '.save']

        if event.is_directory:
            return None
        else:
            newfile = event.src_path.rpartition('/')[2]
            if not any(str in newfile for str in ignorefiles):
                Logger(f'File created: {newfile}')
                hostname = newfile.split('_')[0]
                hostaddr = newfile.split('_')[1]
                x = threading.Thread(target=self.test_ssh, args=(
                    hostname, hostaddr))
                x.start()

    def test_ssh(self, hostname, hostaddr, port=22):

        initialwait = 15
        retrywait = 3
        attempts = 0
        maxattempts = 25

        Logger(f'{hostname}: Attempting SSH to {hostaddr} in {initialwait}s.')
        time.sleep(initialwait)

        result = None
        while result is None:
            try:
                attempts += 1
                testconn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testconn.connect((hostaddr, port))
            except Exception as e:
                if attempts >= maxattempts:
                    Logger(
                        f'{hostname}: SSH attempts exhausted ({maxattempts}); {e}.')
                    break
                else:
                    time.sleep(retrywait)
                    continue
            else:
                result = testconn
                testconn.close()
                Logger(
                    f'{hostname}: SSH connection success after {attempts} attempt(s) -> copy image file.')
                self.os_upgrade(hostname, hostaddr)
                break

    def os_upgrade(self, hostname, hostaddr):

        Logger(f'{hostname}: Starting TFTP image transfer.')

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
        copystart = time.time()
        copyfile = nr.run(
            task=netmiko_send_command,
            command_string=f'copy tftp://{tftpaddr}/{imgfile} flash:',
            delay_factor=6,
        )
        copyduration = round(time.time() - copystart)
        # std_log(copyfile)
        Logger(
            f'{hostname}: Image transfer completed after {copyduration}s -> set boot variable.')

        bootcmds = f'default boot sys\nboot system flash:{imgfile}'
        bootcmds_list = bootcmds.splitlines()
        bootvar = nr.run(
            task=netmiko_send_config,
            config_commands=bootcmds_list
        )
        # std_log(bootvar)
        Logger(f'{hostname}: Boot variable set -> write config.')

        writemem = nr.run(
            task=netmiko_send_command,
            command_string='write mem',
        )
        # std_log(writemem)
        Logger(f'{hostname}: Config written, ready to reload/power off.')
        nr.close_connections()


if __name__ == '__main__':

    with open('./ztpconfig.yaml', 'r') as f:
        config = yaml.safe_load(f)

    logfile = config['logfile']
    watch_dir = config['watch_dir']
    tftpaddr = config['tftpaddr']
    imgfile = config['imgfile']
    username = config['username']
    password = config['password']

    w = Watcher()
    w.run()
