#!/usr/bin/env python
# Copyright 2011 The greplin-exception-catcher Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Cron for sending exception logs to greplin-exception-catcher.

Usage: upload.py http://server.com secretKey exceptionDirectory
"""

import json
import os
import time
import os.path
import shutil
import stat
import sys
import urllib2

FILES_TO_KEEP = 2000
SETTINGS = {}




def reportTooManyExceptions(deleted, example):
  """Report a special message to the GEC server if we see too many exceptions."""
  newErr = {
    "project": "GEC",
    "environment": example["environment"],
    "serverName": example["serverName"],
    "message": "Too many exceptions - GEC deleted %d" % deleted,
    "timestamp": int(time.time())
  }
  sendException(newErr, "NoFilename")


def sendException(jsonData, filename):
  """Send an exception to the GEC server
     Returns True if sending succeeded
     If the send fails, returns False and moves the file to '_' + filename"""


  def handleError(e, message):
    """Handles an error by printing it and marking the file as available but with an additional strike."""
    print message % filename
    print e
    if filename != 'NoFilename':
      shutil.move(filename + '.processing', os.path.join(os.path.dirname(filename), '_' + os.path.basename(filename)))


  request = urllib2.Request('%s/report?key=%s' % (SETTINGS["server"], SETTINGS["secretKey"]),
                            json.dumps(jsonData),
                            {'Content-Type': 'application/json'})
  try:
    response = urllib2.urlopen(request)

  except urllib2.HTTPError, e:
    handleError(e, 'Error from server while uploading %s')
    print e.read()
    return False

  except urllib2.URLError, e:
    handleError(e, 'Error while uploading %s')
    return False

  status = response.getcode()

  if status != 200:
    raise Exception('Unexpected status code: %d' % status)

  return True


def processFiles(files):
  """Sends each exception file in files to gec"""

  # only keep the newest FILES_TO_KEEP entries
  outstanding = len(files)
  if outstanding > FILES_TO_KEEP:
    deleted = outstanding-FILES_TO_KEEP
    files = sorted(files, key=os.path.getctime)
    with open(files[0]) as f:
      reportTooManyExceptions(deleted, json.load(f))
    [os.remove(f) for f in files[0:deleted] if os.path.exists(f)]
    files = files[deleted:]


  for filename in files:
    if os.path.exists(filename):
      try:
        timestamp = os.stat(filename)[stat.ST_CTIME]
      except OSError:
        # Usually this happens when another process processes the same file.
        continue

      processingFilename = filename + '.processing'
      try:
        shutil.move(filename, processingFilename)
      except IOError:
        # Usually this happens when another process processes the same file.
        continue
      try:
        with open(processingFilename) as f:
          result = json.load(f)
      except ValueError, ex:
        with open(processingFilename) as f:
          print >> sys.stderr, "Could not read %s:" % filename
          print >> sys.stderr, '\n------------------\n'
          print >> sys.stderr, f.read()
          print >> sys.stderr, '\n------------------\n'
          print >> sys.stderr, str(ex)
        os.remove(processingFilename)
        continue
      result['timestamp'] = timestamp

      # Only delete on success - otherwise the file was moved
      if sendException(result, filename):
        os.remove(processingFilename)


def writePid(lockDir):
  """Writes the current pid to the lock directory."""
  with open(os.path.join(lockDir, 'pid'), 'w') as f:
    f.write(str(os.getpid()))


def main():
  """Runs the gec sender."""

  if len(sys.argv) not in (3, 4):
    print """USAGE: upload.py SERVER SECRET_KEY PATH [LOCKNAME]

LOCKNAME defaults to 'upload-lock'"""
    exit(-1)


  SETTINGS["server"] = sys.argv[1]
  SETTINGS["secretKey"] = sys.argv[2]
  path = sys.argv[3]

  lockName = sys.argv[4] if len(sys.argv) == 5 else 'upload-lock'
  lock = os.path.join(path, lockName)

  # mkdir will fail if the directory already exists, so we can use it as a file lock
  try:
    os.mkdir(lock)
    writePid(lock)
  except OSError:
    blocked = True
    try:
      with open(os.path.join(lock, 'pid')) as f:
        pid = int(f.read().strip())
      os.kill(pid, 0)
    except (IOError, ValueError, OSError):
      # No pid file, bad pid file, or pid doesn't exit.
      writePid(lock)
      blocked = False

    if blocked:
      print "Lock directory '%s' already exists." % lock
      print "Another upload.py appears to be running. Consider killing it and trying again."
      exit(-1)

  files = [os.path.join(path, f) for f in os.listdir(path)
           if f.endswith(".gec.json") and not '_____' in f]

  try:
    processFiles(files)
  finally:
    try:
      os.unlink(os.path.join(lock, 'pid'))
    except IOError:
      print >> sys.stderr, 'Tried to delete nonexistent pid file %r' % os.path.join(lock, 'pid')
      print >> sys.stderr, 'Lock directory %r existence status: %r' % os.path.exists(lock)
      if os.path.exists(lock):
        print >> sys.stderr, 'Lock directory contents: %r' % os.listdir(lock)
    try:
      os.rmdir(lock)
    except OSError:
      print >> sys.stderr, 'Could not delete lock directory %r (exists: %r)' % (lock, os.path.exists(lock))
      if os.path.exists(lock):
        print >> sys.stderr, 'Lock directory exists.'
        print >> sys.stderr, 'Lock directory contents: %r' % os.listdir(lock)


if __name__ == '__main__':
  main()
