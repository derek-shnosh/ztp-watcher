# (Free)ZTP Watcher

Watches specified directory for [FreeZTP][freeztp] custom merged-config files which are created after a switch is successfully provisioned. File name is parsed for hostname and host IP address to initiate a TFTP transfer of the specified IOS image.

> _TFTP preferred over SCP due to speed (include `ip tftp blocksize 8192` in the switch template) and because FreeZTP has TFTP built-in so no additional services are required._

_**Use-case**_: Copy IOS image .bin file to C2960S/X/XR switches post FreeZTP provisioning to avoid the auto-install function using a .tar file (lengthy process).

![screenshot-cisco-ref][ss-cisco-ref]

[Source][cisco-doc]

## Considerations

- Ensure that FreeZTP **imagediscoveryfile-option** is set to **disable**.

   ```bash
   ztp set dhcpd INTERFACE-{dhcp_interface} imagediscoveryfile-option disable
   ```

- It is imperative that your `keystore_id` value does *not* have an underscore (`_`) in it.

- Custom merged-config file syntax must begin with **{{keystore_id}}_{{ipaddr}}**; e.g.

   `{{keystore_id}}_{{ipaddr}}_{{idarray|join("-")}}_merged.cfg`

   _**Full custom log file config example...**_

   ```bash
   ztp set logging merged-config-to-custom-file '/etc/ztp/logs/merged/{{keystore_id}}_{{ipaddr}}_{{idarray|join("-")}}_merged.cfg'
   ```

   \*_**Suggestion**_: Disable logging merged configs to the main log file via;

    ```bash
     ztp set logging merged-config-to-mainlog disable
    ```

## Installation/Usage

1. Install Python3 dependencies.

   ```bash
   pip install nornir
   pip install nornir-netmiko
   pip install pyyaml
   pip install watchdog
   ```

2. Clone repo to desired location.

   ```bash
   sudo git clone {URL} /var/git/ztp-watcher
   ```

3. Make a copy of **ztpconfig_sample.yaml** as **ztpconfig.yaml** and edit for environment.

   > See **ztpconfig_sample.yaml* file for explanation of options.

   ```bash
   sudo cp /var/git/ztp-watcher/ztpconfig_sample.yaml /var/git/ztp-watcher/ztpconfig.yaml
   sudo nano /var/git/ztp-watcher/ztpconfig.yaml
   ```

   - _**Edit values accordingly**_

     ```yaml
     logfile: /etc/ztp/logs/ztpwatcher.log
     watch_dir: /etc/ztp/logs/merged/
     ssh_method: ip
     tftpaddr: 172.17.251.251
     imgfile: c2960x-universalk9-mz.152-4.E8.bin
     username: cisco
     password: cisco
     ```

4. Edit **ztp-watcher.service** systemd unit file with path.

   ```bash
   sudo nano /var/git/ztp-watcher/ztp-watcher.service
   ```

   - _**Edit `ExecStart` and `WorkingDirectory` paths accordingly**_

     ```bash
     ...
     ExecStart=/bin/bash -c 'cd /var/git/ztp-watcher; python3 ztp-watcher.py'
     WorkingDirectory=/var/git/ztp-watcher/
     ...
     ```

5. Copy **.service** file to **/etc/systemd/system/**, then enable and start it.

   ```bash
   sudo cp /var/git/ztp-watcher/ztp-watcher.service /etc/systemd/system/
   sudo systemctl enable ztp-watcher.service
   sudo systemctl start ztp-watcher.service
   ```

## References

- https://github.com/PackeTsar/freeztp/
- https://github.com/torfsen/python-systemd-tutorial
- https://pynet.twb-tech.com/blog/nornir/intro.html
- https://pynet.twb-tech.com/blog/nornir/os-upgrade-p1.html
- https://www.michaelcho.me/article/using-pythons-watchdog-to-monitor-changes-to-a-directory

[freeztp]: https://github.com/PackeTsar/freeztp/
[cisco-doc]: https://www.cisco.com/c/en/us/td/docs/solutions/Enterprise/Plug-and-Play/release/notes/pnp-release-notes16.html#pgfId-206873
[ss-cisco-ref]: assets/images/cisco-ref.png
