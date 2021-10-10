#!/usr/bin/env python3

import paramiko
import epics
import os
import time
import re
from gemlogconflib import gemlogconf
from datetime import datetime, timedelta

# Environment information for AOM and NGS2 IOCs
AOMIP = '172.17.65.100'
NGS2IP = '172.17.65.31'
NGS2USER = 'software'
NGS2PASS = 'Aliquamliber0!'
NGS2CMD = '/opt/ao/bin/aocmd "tcp://localhost:45000" "STATUS"'
TEMP_HHL = 50 # Nuvu camera Temperature limit in Celsius

os.environ['EPICS_CA_ADDR_LIST'] = NGS2IP + ' ' + AOMIP

# Definitions for log handling
LOGPATH = '/gemsoft/var/log/nuvuMon/'
LOGFILENAME = 'nuvuMon.log'
CONFFILENAME = 'nuvuMonLog.conf'
LOGFILE = LOGPATH + LOGFILENAME
CONFIGFILE = LOGPATH + CONFFILENAME
ROTATION_HOUR = 8 # Rotation hour, integer from 0 - 23 (24hr time)

if __name__ == '__main__':
    temp_flag = False
    # If script starts and log file exists, assume the script restarted. Move
    # existing file to name with restart date.
    if os.path.isfile(LOGFILE):
        restart_time = datetime.now().strftime("R%Y%m%dT%H%M%S")
        restart_file = LOGFILE + '.' + restart_time
        try:
            sp.run(['mv', LOGFILE, restart_file])
        except Exception as e:
            print(e)
    # Initialize time rotating log
    nuvu_log = gemlogconf.init_timertng_log(CONFIGFILE, LOGFILE, ROTATION_HOUR)
    nuvu_log.info('************ NUVU Temperature Monitor Start ************')
    # Make connection to Nuvu Temperature record on AOM IOC
    try:
        ngs2nvtemp = epics.PV('aom:ngs2:tempNuvu')
    except Exception as e:
        nuvu_log.exception(str(e))
        exit(0)

    # Make ssh connection to NGS2 rtc
    try:
        ngs2 = paramiko.SSHClient()
        ngs2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ngs2.connect(NGS2IP, username=NGS2USER, password=NGS2PASS)
    except Exception as e:
        nuvu_log.exception(str(e))
        exit(0)

    # Sleep to give time to slow connection to return valid state
    time.sleep(0.25)

    # Loop forever to update temperature
    while True:
        startWhile = datetime.now()  # Used to calculate total loop time
        nuvuTemp = ''
        # Execute aocmd on NGS2 rtc
        try:
            stdin, stdout, stderr = ngs2.exec_command(NGS2CMD)
        except Exception as e:
            nuvu_log.exception(str(e))
            time.sleep(60)
            continue

        for line in stdout:
            # Search for camera body temp on aocmd STATUS output
            tempsrch = re.search('body', line)
            if tempsrch is not None:
                nuvuTemp = line.split('=')[1]

        # If there's no reading from NGS2, assume is down and publish nonsensical
        # temperature, else publish Nuvu Cam Temp
        try:
            if nuvuTemp == '':
                ngs2nvtemp.put(float('nan'))
                nuvu_log.error('Null temperature')
            else:
                ngs2nvtemp.put(nuvuTemp)
                nuvu_log.debug('Temperature: {0}'.format(nuvuTemp))
        except Exception as e:
            nuvu_log.exception(str(e))
            time.sleep(10)
            continue
        # Jank switch statement below!!
        while nuvuTemp:
            # If temp is higher than high limit, print error
            if float(nuvuTemp) > TEMP_HHL:
                nuvu_log.error(f"Nuvu Temperature > {TEMP_HHL}: {nuvuTemp}")
                temp_flag = 1
                break
            # Print temperature out to log, but only on the first looping or after
            # the temperature is cooled to below the high limit
            temp_okmsg = (f"Temperature < {TEMP_HHL}: {nuvuTemp}"
                            * (1 - temp_flag))
            temp_flag += (1 - temp_flag)
            if temp_okmsg:
                nuvu_log.info(temp_okmsg)
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

    ngs2.close()  # Close ssh connection
