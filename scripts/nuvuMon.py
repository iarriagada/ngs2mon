#!/usr/bin/env python3

import paramiko
import epics
import os
import time
import re
import subprocess as sp
from gemlogconflib import gemlogconf
from datetime import datetime, timedelta

# Environment information for AOM and NGS2 IOCs
AOMIP = '172.17.65.100'
NGS2IP = '172.17.65.31'
NGS2USER = 'software'
NGS2SSHKEY = '/home/software/.ssh/id_rsa'
NGS2CMD = '/opt/ao/bin/aocmd "tcp://localhost:45000" "STATUS"'
BODY_TEMP_HL = 50 # Nuvu Body Temperature limit in Celsius
CCD_TEMP_HL = -65 # Nuvu CCD Temperature limit in Celsius
BODY_TEMP_CHAN = 'aom:ngs2:tempNuvuBody'
CCD_TEMP_CHAN = 'aom:ngs2:tempNuvuCCD'

os.environ['EPICS_CA_ADDR_LIST'] = NGS2IP + ' ' + AOMIP

# Definitions for log handling
LOGPATH = '/gemsoft/var/log/nuvuMon/'
LOGFILENAME = 'nuvuMon.log'
CONFFILENAME = 'nuvuMonLog.conf'
LOGFILE = LOGPATH + LOGFILENAME
CONFIGFILE = LOGPATH + CONFFILENAME
ROTATION_HOUR = 8 # Rotation hour, integer from 0 - 23 (24hr time)

def ssh_connection(ip, user, ssh_key, log_handler):
    # Make ssh connection to NGS2 rtc
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(ip, username=user, key_filename=ssh_key)
    except Exception as e:
        log_handler.exception(str(e))
        exit(0)
    return ssh_client

if __name__ == '__main__':
    body_flag = False
    ccd_flag = False
    # If script starts and log file exists, assume the script restarted. Move
    # existing file to name with restart date.
    # TODO: Check why the section below is not working when deployed.
    if os.path.isfile(LOGFILE):
        restart_time = datetime.now().strftime("R%Y%m%dT%H%M%S")
        restart_file = LOGFILE + '.' + restart_time
        try:
            sp.run(['mv', LOGFILE, restart_file])
        except Exception as e:
            print(e)
    # Initialize time rotating log
    nuvu_log = gemlogconf.init_timertng_log(CONFIGFILE, LOGFILE, ROTATION_HOUR)
    nuvu_log.info('************ NUVU CAMERA Temperature Monitor Start ************')
    # Make connection to Nuvu Temperature record on AOM IOC
    try:
        ngs2bodytemp = epics.PV(BODY_TEMP_CHAN)
        ngs2ccdtemp = epics.PV(CCD_TEMP_CHAN)
    except Exception as e:
        nuvu_log.exception(str(e))
        exit(0)

    ngs2_client = ssh_connection(NGS2IP, NGS2USER, NGS2SSHKEY, nuvu_log)

    # Sleep to give time to slow connection to return valid state
    time.sleep(0.25)

    # Loop forever to update temperature
    while True:
        startWhile = datetime.now()  # Used to calculate total loop time
        temp_body = ''
        temp_ccd = ''
        # Execute aocmd on NGS2 rtc
        try:
            stdin, stdout, stderr = ngs2_client.exec_command(NGS2CMD)
        except Exception as e:
            nuvu_log.exception(str(e))
            ngs2_client.close()
            time.sleep(60)
            ngs2_client = ssh_connection(NGS2IP, NGS2USER, NGS2SSHKEY, nuvu_log)
            continue

        for line in stdout:
            if temp_body and temp_ccd:
                break
            # Search for camera body temp on aocmd STATUS output
            tempsrch = re.search('body', line)
            if tempsrch is not None:
                temp_body = line.split('=')[1]
                continue
            # Search for camera ccd temp on aocmd STATUS output
            tempsrch = re.search('ccd', line)
            if tempsrch is not None:
                temp_ccd = line.split('=')[1]
                continue

        # If there's no reading from NGS2, assume is down and publish nonsensical
        # temperature, else publish Nuvu Cam Temp
        if not(temp_body or temp_ccd):
            temp_body = float('nan')
            temp_ccd = float('nan')
            nuvu_log.error('Body and CCD Null temperature. Check cpongs2-lp1')
        else:
            nuvu_log.debug('Body Temperature: {0}'.format(temp_body))
            nuvu_log.debug('CCD Temperature: {0}'.format(temp_ccd))
        # Put values in EPICS records and capture result. Compose error message
        # if channels are disconnected
        body_put = ngs2bodytemp.put(temp_body)
        ccd_put = ngs2ccdtemp.put(temp_ccd)
        body_ca_msg = f'{BODY_TEMP_CHAN} is disconnected!!!'
        ccd_ca_msg = f'{CCD_TEMP_CHAN} is disconnected!!!'
        full_msg = (body_ca_msg * bool(not(body_put)) +
                    ccd_ca_msg * bool(not(ccd_put)))
        if full_msg:
            nuvu_log.error(full_msg)
        # Jank switch statements below!! I did it mostly because I hate if
        # statements
        while temp_body:
            # If temp is higher than high limit, print error
            if float(temp_body) > BODY_TEMP_HL:
                nuvu_log.error(f"Body Temperature > {BODY_TEMP_HL}: {temp_body}")
                body_flag = 1
                break
            # Print temperature out to log, but only on the first looping or after
            # the temperature is cooled to below the high limit
            body_okmsg = (f"Body Temperature < {BODY_TEMP_HL}: {temp_body}"
                            * (1 - body_flag))
            body_flag += (1 - body_flag)
            if body_okmsg:
                nuvu_log.info(body_okmsg)
            break
        while temp_ccd:
            # If temp is higher than high limit, print error
            if float(temp_ccd) > CCD_TEMP_HL:
                nuvu_log.error(f"CCD Temperature > {CCD_TEMP_HL}: {temp_ccd}")
                ccd_flag = 1
                break
            # Print temperature out to log, but only on the first looping or after
            # the temperature is cooled to below the high limit
            ccd_okmsg = (f"CCD Temperature < {CCD_TEMP_HL}: {temp_ccd}"
                            * (1 - ccd_flag))
            ccd_flag += (1 - ccd_flag)
            if ccd_okmsg:
                nuvu_log.info(ccd_okmsg)
            break
        # Calculate while loop exec time
        currTime = datetime.now()
        loopTime = (currTime - startWhile).total_seconds()
        nuvu_log.debug('Loop time: {0}'.format(loopTime))
        waitTime = 10 - loopTime
        if loopTime > 10:
            nuvu_log.error('Loop took too long')
            continue

        # Wait until checking again
        time.sleep(waitTime)

    ngs2_client.close()  # Close ssh connection
