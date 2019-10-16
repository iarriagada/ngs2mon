#!/usr/bin/env python3

import paramiko
import epics
import os
import time
import re
from datetime import datetime, timedelta

# Environment information for AOM and NGS2 IOCs
AOMIP = '172.17.65.100'
NGS2IP = '172.17.65.31'
NGS2USER = 'root'
NGS2PASS = 'ngs2@cERROp'
NGS2CMD = '/opt/ao/bin/aocmd "tcp://localhost:45000" "STATUS"'
os.environ['EPICS_CA_ADDR_LIST'] = NGS2IP + ' ' + AOMIP
# Make connection to Nuvu Temperature record on AOM IOC
ngs2nvtemp = epics.PV('aom:ngs2:tempNuvu')
# Make ssh connection to NGS2 rtc
ngs2 = paramiko.SSHClient()
ngs2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ngs2.connect(NGS2IP, username=NGS2USER, password=NGS2PASS)
time.sleep(0.2) # Sleep to give time to slow connection to return valid state
# Loop forever to update temperature
while(True):
    startWhile = datetime.now() # Used to calculate total loop time
    nuvuTemp = ''
    # Execute aocmd on NGS2 rtc
    stdin, stdout, stderr = ngs2.exec_command(NGS2CMD)
    for line in stdout:
        # Search for camera body temp on aocmd STATUS output
        tempsrch = re.search('body', line)
        if not(tempsrch == None):
            nuvuTemp = line.split('=')[1]
    # If there's no reading from NGS2, assume is down and publish nonsensical
    # temperature, else publish Nuvu Cam Temp
    if nuvuTemp == '':
        ngs2nvtemp.put(float(NaN))
    else:
        ngs2nvtemp.put(nuvuTemp)
    # Calculate while loop exec time
    currTime = datetime.now()
    loopTime = (currTime - startWhile).total_seconds()
    waitTime = 10 - loopTime
    if loopTime > 10:
        print("Loop took too long: {0} [s]".format(loopTime))
        continue
    # Wait until checking again
    time.sleep(waitTime)
ngs2.close() # Close ssh connection

