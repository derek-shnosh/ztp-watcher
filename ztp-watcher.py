#!/usr/bin/python3
# Author: DS, shnosh.io


import time
import threading
import logging
import yaml
import socket
import re
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from nornir import InitNornir
from nornir.plugins.tasks.networking import netmiko_send_command, netmiko_send_config


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
        Logger('ZTP Watcher fully loaded and running.')
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
    # When a file is created, the filename is parsed for hostname and IP address,
    # and the file text is parsed for any IP address found in the configuration.
    # These values are passed to the `test_ssh` function to validate SSH reachability.
    def on_created(self, event):

        ignorefiles = ['.swp', '.save']

        if event.is_directory:
            return None
        else:
            newfile = event.src_path
            filename = newfile.rpartition('/')[2]
            if not any(str in filename for str in ignorefiles):
                Logger(f'New file detected: {filename}')
                hostname = filename.split('_')[0]
                hostaddr = filename.split('_')[1]
                if ssh_method == 'parse':
                    time.sleep(2)
                    config = open(newfile).read()
                    ipaddr = re.search(r'ip\saddress\s([\d\.]+)', config).group(1) or ''
                else:
                    ipaddr = None
                x = threading.Thread(target=self.test_ssh, args=(hostname, hostaddr, ipaddr))
                x.start()

    # `test_ssh` function validates that the IP address parsed from the `on_created`
    # function will accept SSH connections (auth attempts are not yet made).
    # The hostname and IP address are passed to the `os_upgrade` function to update
    # the provisioned switches.
    def test_ssh(self, hostname, hostaddr, ipaddr, port=22):

        conn = (hostname if ssh_method == 'dns' else
                hostaddr if ssh_method == 'ip' else
                ipaddr if ssh_method == 'parse' else '')

        Logger(f'{hostname}: Verifying SSH reachability to {conn} in {ssh_initialwait}s.')
        time.sleep(ssh_initialwait)
        result = None
        ssh_attempts = 0
        while result is None:
            try:
                ssh_attempts += 1
                testconn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testconn.settimeout(ssh_timeout)
                testconn.connect((conn, port))
            except Exception as e:
                if ssh_attempts >= ssh_maxattempts:
                    result = testconn
                    Logger(f'{hostname}: SSH verification attempts exhausted ({ssh_maxattempts}); {e}.')
                    quit()
                else:
                    time.sleep(ssh_retrywait)
                    continue
            else:
                result = testconn
                testconn.close()
                Logger(f'{hostname}: SSH reachability verified after {ssh_attempts} attempt(s).')
                self.os_upgrade(hostname, conn)

    # `os_upgrade` function copies the .bin image via TFTP, sets the boot var,
    # and writes the config.
    def os_upgrade(self, hostname, conn):

        def get_output(agg_result):
            for k, multi_result in agg_result.items():
                for result_obj in multi_result:
                    return result_obj.result

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

        # Initiate Nornir connection to switch.
        nr = InitNornir(
            inventory={
                'options': {
                    'hosts': {
                        hostname: {
                            'hostname': conn,
                            'username': username,
                            'password': password,
                            'platform': 'ios'
                        }
                    }
                }
            }
        )

        # Check flash: on switch for image file specified in ztpconfig.yaml.
        Logger(f'{hostname}: Connecting via SSH to check for image file on switch.')
        checkimg = send_cmd(f'dir flash:{imgfile}')
        output = get_output(checkimg)
        if '%Error' not in output:
            # Image file already in flash, skip transfer.
            Logger(f'{hostname}: Image file already present on switch ({imgfile}), skipping transfer.')
            sw_log(f'Image file already present ({imgfile}), skipping transfer.')
        else:
            # Image file not found, initiate TFTP transfer.
            Logger(f'{hostname}: Image file not found on switch ({imgfile}), starting TFTP transfer.')
            sw_log(f'Image file not found ({imgfile}), starting image transfer via TFTP.')
            copystart = time.time()
            copyfile = send_cmd(f'copy tftp://{tftpaddr}/{imgfile} flash:')
            copyduration = round(time.time() - copystart)
            copystatus = get_output(copyfile)
            if 'Error' not in copystatus:
                Logger(f'{hostname}: Image transfer completed after {copyduration}s -> set boot variable.')
                sw_log('Image transfer complete -> set boot variable.')
                # Set boot variable on switch.
                bootcmds = f'default boot sys\nboot system flash:{imgfile}'
                bootcmds_list = bootcmds.splitlines()
                send_config(bootcmds_list)
                Logger(f'{hostname}: Boot variable set -> write config.')
                sw_log('Boot variable set -> write config.')
            elif 'OSError' in copystatus:
                Logger(f'{hostname}: ***Unhandled prompt, put `file prompt quiet` in switch config/template.')
                sw_log('***Unhandled prompt, put `file prompt quiet` in switch config/template.')
            elif '%Error' in copystatus:
                Logger(f'{hostname}: ***Image transfer failed after {copyduration}s; {copystatus}')
                sw_log('***Image transfer failed.')

        # Send post-provisioning configuration commands to switch.
        if post_cfg:
            Logger(f'{hostname}: Sending post provisioning configurations.')
            sw_log('Sending post provisioning configurations.')
            postcfg_list = postcfg.splitlines()
            send_config(postcfg_list)

        # Push final config back to TFTP server.
        if cfg_push:
            Logger(f'{hostname}: Pushing final running config to TFTP server ({tftpaddr}/{cfg_push}/{hostname}.cfg).')
            sw_log(f'Pushing final config to TFTP server ({tftpaddr}/{cfg_push}/{hostname}.cfg).')
            send_cmd(f'copy run tftp://{tftpaddr}/{cfg_push}/{hostname}.cfg')

        # Write configuration to switch.
        sw_log('Writing configuration to startup.')
        send_cmd('write mem')
        Logger(f'{hostname}: Config written, ready to reload/power off.')
        sw_log('Config written, ready to reload/power off.')

        # Close nornir connection to switch.
        nr.close_connections()


if __name__ == '__main__':
    # Open the `ztpconfig.yaml` file to parse configuration settings.
    try:
        with open('ztpconfig.yaml', 'r') as f:
            config = yaml.safe_load(f)
            # globals().update(config) #Works, but linter complains about invalid vars.

        logfile = config['logfile']
        watch_dir = config['watch_dir']
        ssh_method = config['ssh_method']
        post_cfg = config['post_cfg']
        cfg_push = config['cfg_push']
        tftpaddr = config['tftpaddr']
        imgfile = config['imgfile']
        username = config['username']
        password = config['password']
        ssh_initialwait = config['ssh_initialwait']
        ssh_timeout = config['ssh_timeout']
        ssh_retrywait = config['ssh_retrywait']
        ssh_maxattempts = config['ssh_maxattempts']
    except FileNotFoundError:
        print('ERROR: Configuration file not found (ztpconfig.yaml), quitting.')
        quit()

    Logger(f'OK - Configuration file found (ztpconfig.yaml).')

    # Get contents of the configured post provisioning config file.
    if post_cfg:
        try:
            with open(post_cfg, 'r') as f:
                postcfg = f.read()
                Logger(
                    f'OK - Post provisioning configuration file loaded ({post_cfg}).')
        except FileNotFoundError:
            Logger(
                f'WARNING: Post provisioning configuration file not found ({post_cfg}).')
            post_cfg = ''

    w = Watcher()
    w.run()
