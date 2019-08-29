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


# Open the `ztpconfig.yaml` file to parse configuration settings.
with open('./ztpconfig.yaml', 'r') as f:
    config = yaml.safe_load(f)

logfile = config['logfile']
watch_dir = config['watch_dir']
tftpaddr = config['tftpaddr']
imgfile = config['imgfile']
username = config['username']
password = config['password']


# `Logger` class to handle logging messages to file.
class Logger:

    def __init__(self, logdata):
        logging.basicConfig(format='%(asctime)s %(message)s',
                            datefmt='%Y/%m/%d %I:%M:%S %p',
                            filename=logfile,
                            level=logging.INFO)
        logging.info(f'-- {logdata}')
        print(f'\n{logdata}')


# `Watcher` class to watch the specified directory for new files.
class Watcher:

    def __init__(self):
        self.observer = Observer()

    def run(self):
        event_handler = Handler()
        self.observer.schedule(event_handler, watch_dir, recursive=False)
        self.observer.start()
        Logger('ZTP Watcher started.')
        try:
            while True:
                time.sleep(5)

        except KeyboardInterrupt:
            self.observer.stop()
            Logger('ZTP Watcher stopped (keyboard interrupt).')

        except:
            self.observer.stop()
            Logger('Error.')


# `Handler` class to validate SSH reachability and initiate .bin file firmware
# update to provisioned switches.
class Handler(FileSystemEventHandler):

    # `on_created` function uses threading to start the update.
    # When a file is created, the filename is parsed for hostname and IP address.
    # These values are passed to the `test_ssh` function to validate SSH reachability.
    def on_created(self, event):

        ignorefiles = ['.swp', '.save']

        if event.is_directory:
            return None
        else:
            newfile = event.src_path.rpartition('/')[2]
            if not any(str in newfile for str in ignorefiles):
                Logger(f'New file detected: {newfile}')
                hostname = newfile.split('_')[0]
                hostaddr = newfile.split('_')[1]
                x = threading.Thread(target=self.test_ssh, args=(
                    hostname, hostaddr))
                x.start()

    # `test_ssh` function validates that the IP address parsed from the `on_created`
    # function will accept SSH connections (auth attempts are not yet made).
    # The hostname and IP address are passed to the `os_upgrade` function to update
    # the provisioned switches.
    def test_ssh(self, hostname, hostaddr, port=22):

        initialwait = 15
        retrywait = 3
        attempts = 0
        maxattempts = 20

        Logger(
            f'{hostname}: Verifying SSH reachability to {hostaddr} in {initialwait}s.')
        time.sleep(initialwait)

        result = None
        while result is None:
            try:
                attempts += 1
                testconn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testconn.connect((hostaddr, port))
            except Exception as e:
                if attempts >= maxattempts:
                    result = testconn
                    Logger(
                        f'{hostname}: SSH verification attempts exhausted ({maxattempts}); {e}.')
                else:
                    time.sleep(retrywait)
                    continue
            else:
                result = testconn
                testconn.close()
                Logger(
                    f'{hostname}: SSH reachability verified after {attempts} attempt(s) -> copy image file.')
                self.os_upgrade(hostname, hostaddr)

    # `os_upgrade` function copies the .bin image via TFTP, sets the boot variable,
    # and writes the config.
    def os_upgrade(self, hostname, hostaddr):

        # `std_log` function to parse nr.run() output, use for TS.
        def std_log(agg_result):
            for k, multi_result in agg_result.items():
                for result_obj in multi_result:
                    Logger(f'{k}\n{result_obj.result}')

        # 'sw_log' function sends syslog messages to the switch.
        def sw_log(logmsg):
            result = nr.run(
                task=netmiko_send_command,
                command_string=f'send log ZTP-Watcher: {logmsg}',
            )
            return(result)

        # 'send_cmd' function sends commands to the host.
        def send_cmd(cmd):
            result = nr.run(
                task=netmiko_send_command,
                command_string=cmd,
                delay_factor=6,
            )
            return(result)

        # 'send_config' function sends configuration commands to the host.
        def send_config(config):
            result = nr.run(
                task=netmiko_send_config,
                config_commands=config
            )
            return(result)

        Logger(f'{hostname}: Connecting via SSH and starting TFTP image transfer.')

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

        sw_log('Starting .bin image transfer via TFTP.')
        copystart = time.time()
        copyfile = send_cmd(f'copy tftp://{tftpaddr}/{imgfile} flash:')
        copyduration = round(time.time() - copystart)
        sw_log('Image transfer complete.')
        Logger(
            f'{hostname}: Image transfer completed after {copyduration}s -> set boot variable.')
        # std_log(copyfile)                                   # Uncomment for TS

        sw_log('Setting boot variable and writing config.')
        bootcmds = f'default boot sys\nboot system flash:{imgfile}'
        bootcmds_list = bootcmds.splitlines()
        bootvar = send_config(bootcmds_list)
        Logger(f'{hostname}: Boot variable set -> write config.')
        # std_log(bootvar)                                    # Uncomment for TS

        writemem = send_cmd('write mem')
        Logger(f'{hostname}: Config written, ready to reload/power off.')
        nr.close_connections()
        sw_log('Config written, ready to reload/power off.')
        # std_log(writemem)                                   # Uncomment for TS


if __name__ == '__main__':
    w = Watcher()
    w.run()
