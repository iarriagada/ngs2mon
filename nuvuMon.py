#!/usr/bin/env python3

import paramiko
import epics
import os
import time
import re
import logging
from datetime import datetime, timedelta

# Environment information for AOM and NGS2 IOCs
AOMIP = '172.17.65.100'
NGS2IP = '172.17.65.31'
NGS2USER = 'root'
NGS2PASS = 'ngs2@cERROp'
NGS2CMD = '/opt/ao/bin/aocmd "tcp://localhost:45000" "STATUS"'
os.environ['EPICS_CA_ADDR_LIST'] = NGS2IP + ' ' + AOMIP

logging.basicConfig(filename="nuvu.log", level=logging.INFO, format='%(levelname)s:%(asctime)s: %(message)s')

# Make connection to Nuvu Temperature record on AOM IOC
try:
    ngs2nvtemp = epics.PV('aom:ngs2:tempNuvu')
except Exception as e:
    logging.exception(str(e))
    exit(0)

# Make ssh connection to NGS2 rtc
try:
    ngs2 = paramiko.SSHClient()
    ngs2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ngs2.connect(NGS2IP, username=NGS2USER, password=NGS2PASS)
except Exception as e:
    logging.exception(str(e))
    exit(0)

# Sleep to give time to slow connection to return valid state
time.sleep(0.2)

# Loop forever to update temperature
while True:
    startWhile = datetime.now()  # Used to calculate total loop time
    nuvuTemp = ''
    # Execute aocmd on NGS2 rtc
    try:
        stdin, stdout, stderr = ngs2.exec_command(NGS2CMD)
    except Exception as e:
        logging.exception(str(e))
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
            logging.error('Null temperature')
        else:
            ngs2nvtemp.put(nuvuTemp)
            logging.info('Temperature: {0}'.format(nuvuTemp))
    except Exception as e:
        logging.exception(str(e))
        time.sleep(10)
        continue

    # Calculate while loop exec time
    currTime = datetime.now()
    loopTime = (currTime - startWhile).total_seconds()
    logging.info('Loop time: {0}'.format(loopTime))
    waitTime = 10 - loopTime
    if loopTime > 10:
        logging.error('Loop took too long')
        continue

    # Wait until checking again
    time.sleep(waitTime)

ngs2.close()  # Close ssh connection
