#!/usr/bin/env python3

import paramiko
import epics
import os
import time
import re
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

# Environment information for AOM and NGS2 IOCs
AOMIP = '172.17.65.100'
NGS2IP = '172.17.65.31'
NGS2USER = 'root'
NGS2PASS = 'ngs2@cERROp'
NGS2CMD = '/opt/ao/bin/aocmd "tcp://localhost:45000" "STATUS"'
EMAILS_TO_SEND = ['brojas@gemini.edu']
FROM_EMAIL = 'brojas@gemini.edu'


def on_conn_change(pvname=None, conn=None, **kws):
    """
    Function that detect and it's triggered when the PV connection status changed.
    :param pvname: the name of the PV
    :type pvname: str
    :param conn: the connection status
    :type conn: bool
    :param kws: additional keyword/value arguments
    :type kws: str
    """

    if not conn:
        email_content = 'Channel ' + pvname + ' connection status changed at ' + \
                        datetime.now().ctime() + ' to disconnected.'
        head = 'Timeout connection detected on ' + pvname
        send_email(email_content, head, '', '')


def send_email(content, header, logging_level, day_file):
    """
    Function that send the email of the issue to a specifics persons.
    :param day_file: the date of day
    :type day_file: str
    :param logging_level: the logging level
    :type logging_level: str
    :param header: The email subject
    :type header: str
    :param content: The content of the message
    :type content: str
    """
    if not logging_level and not day_file:
        note = '\n' + '\n' + 'NOTE: Please check ' + logging_level + ' in nuvu' + day_file + '.log' + '\n'
    else:
        note = ''
    for email in EMAILS_TO_SEND:
        msg = MIMEText('\n' + content + note)
        msg['Subject'] = 'NUVU-ALARM: ' + header
        msg['From'] = FROM_EMAIL
        msg['To'] = email
        s = smtplib.SMTP('localhost')
        s.sendmail(FROM_EMAIL, [email], msg.as_string())
        s.quit()
        # print('Email send to ' + email)


if __name__ == '__main__':

    os.environ['EPICS_CA_ADDR_LIST'] = NGS2IP + ' ' + AOMIP
    ssh_attempts_count = 0
    null_temperature_count = 0
    null_temperature_beginning_date = ''
    beginning_date = datetime.today().date()  # Here it's used to know the date when the script start
    logging.basicConfig(filename="nuvu" + str(beginning_date) + ".log",
                        level=logging.INFO, format='%(levelname)s:%(asctime)s: %(message)s')

    # Make connection to Nuvu Temperature record on AOM IOC
    try:
        ngs2nvtemp = epics.PV('aom:ngs2:tempNuvu', connection_callback=on_conn_change)
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
        actual_date = datetime.today().date()  # Used to know the date in each loop
        # If the date from actual_date is later than beginning_date creates a new nuvu.log file
        if actual_date > beginning_date:
            # Remove handler for set basicConfig of the logging again
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)
            logging.basicConfig(filename="nuvu" + str(actual_date) + ".log",
                                level=logging.INFO, format='%(levelname)s:%(asctime)s: %(message)s')
            beginning_date = actual_date  # Set beginning_date to today date, to compare it the next day

        startWhile = datetime.now()  # Used to calculate total loop time
        nuvuTemp = ''

        if ngs2.get_transport().active:
            if ssh_attempts_count > 0:
                # Make email structure when reconnection it's successful
                message = '\n' + "SSH session recovery on host '" + NGS2IP + "' at " \
                          + datetime.now().ctime()
                send_email(message, 'SSH re-connection successful', '', '')
                ssh_attempts_count = 0
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

                    null_temperature_count += 1  # Used to count the times that temperature threw null
                    # If the temperature threw null for first time, send an email
                    if null_temperature_count == 1:
                        null_temperature_beginning_date = datetime.now().ctime()
                        # Make email structure when the temperature is null for first time
                        message = 'Null temperature detected at ' + null_temperature_beginning_date
                        send_email(message, 'Null temperature detected', 'ERROR', str(datetime.today().date()))
                else:
                    print nuvuTemp, datetime.now()
                    ngs2nvtemp.put(nuvuTemp)
                    logging.info('Temperature: {0}'.format(nuvuTemp))

                    # If the temperature threw null more than one time, send an email when temperature stop threw null
                    if null_temperature_count > 1:
                        # Make email structure when the temperature is null
                        message = 'Null temperature detected ' + str(null_temperature_count) + ' times from ' \
                                  + null_temperature_beginning_date + ' to ' + datetime.now().ctime()
                        send_email(message, 'Null temperature detected', 'ERROR', str(datetime.today().date()))
                        null_temperature_count = 0

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

        else:
            logging.error('SSH connection failed')
            ssh_attempts_count += 1
            if ssh_attempts_count > 3:
                # Make email structure when connection failed
                message = '\n' + "Try to reconnect three times SSH connection on host '" + NGS2IP + \
                          "' but wasn't able to restore at " + datetime.now().ctime()
                send_email(message, 'SSH connection failed', 'ERROR', str(datetime.today().date()))
                ssh_attempts_count = 0
                exit(0)
            elif ssh_attempts_count == 1:
                # Make email structure when connection failed for first time
                message = '\n' + "SSH session not active on host '" + NGS2IP + "' at " \
                          + datetime.now().ctime()
                send_email(message, 'SSH connection failed', 'ERROR', str(datetime.today().date()))
            try:
                logging.info('Reconnecting SSH...')
                ngs2.close()
                ngs2.connect(NGS2IP, username=NGS2USER, password=NGS2PASS)
            except Exception as e:
                logging.exception(str(e))
                time.sleep(5)
                continue

    ngs2.close()  # Close ssh connection
