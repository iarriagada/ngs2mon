#!/usr/bin/env python3.5

import paramiko
import epics
import os
import time
import re
from datetime import datetime, timedelta

AOMIP = '172.17.65.100'
NGS2IP = '172.17.65.31'
NGS2USER = 'root'
NGS2PASS = 'ngs2@cERROp'
NGS2CMD = '/opt/ao/bin/aocmd "tcp://localhost:45000" "STATUS"'
os.environ['EPICS_CA_ADDR_LIST'] = NGS2IP + ' ' + AOMIP
ngs2nvtemp = epics.PV('aom:ngs2:tempNuvu')
ngs2 = paramiko.SSHClient()
ngs2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ngs2.connect(NGS2IP, username=NGS2USER, password=NGS2PASS)
# print([line for line in stdout])
# aocmdOut = stdout
# for line in stdout.split('\n'):
while(True):
    startWhile = datetime.now()
    stdin, stdout, stderr = ngs2.exec_command(NGS2CMD)
    for line in stdout:
        # print(line.strip('\n'))
        tempsrch = re.search('body', line)
        if not(tempsrch == None):
            nuvuTemp = line.split('=')[1]
            # print(nuvuTemp)
            ngs2nvtemp.put(float(nuvuTemp))
    currTime = datetime.now()
    loopTime = (currTime - startWhile).total_seconds()
    waitTime = 10 - loopTime
    if loopTime > 10:
        print("Loop took too long: {0} [s]".format(loopTime))
        continue
    time.sleep(waitTime)
ngs2.close()

