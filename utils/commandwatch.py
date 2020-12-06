import re
import sys
from subprocess import PIPE, Popen
from threading import Thread
from queue import Queue, Empty
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

class CommandWatch():
    """
    CommandWatch runs given command and checks number of times given regex is encountered from the output of command.
    It records and returns time taken beginning from first line of output or first time start pattern is encountered.
    It can optionally be set to run for specified length of time.
    """
    q = Queue()
    p = None
    readThread = None
    countdown = 0
    end_pattern = None
    start_pattern = None
    cmd = None

    class Enqueue(Thread):
        out = None
        queue = None

        def __init__(self, out, queue):
            super().__init__()
            self.out = out
            self.daemon = True
            self.queue = queue

        def run(self) -> None:
            for line in iter(self.out.readline, b''):
                self.queue.put(line)
            self.out.stdout.close()

    def __init__(self, cmd, countdown, end_pattern, start_pattern=None):
        """
        @param cmd: Command to run
        @param countdown: Check end_pattern is matched as many times from cmd output
        @param end_pattern: pattern to match for countdown
        @param start_pattern: Optional start of timer
        """
        self.cmd = cmd
        self.countdown = countdown
        self.end_pattern = re.compile(end_pattern)
        if start_pattern:
            self.start_pattern = re.compile(start_pattern)

    def submit(self, timer=0):
        self.p = Popen([self.cmd], stdout=PIPE, bufsize=1,
                       universal_newlines=True, shell=True, executable='/bin/bash', preexec_fn=os.setsid)
        self.readThread = CommandWatch.Enqueue(self.p.stdout, self.q)
        executor = ThreadPoolExecutor(1)
        future = executor.submit(self.run, timer)
        return future

    def run(self, timer=0):
        """
        Run command and record running time
        @param timer: Run for given number of seconds, Optional (defaults to 0, meaning run forever or till pattern is matched count number of times)
        @return:
        """
        if not self.p:
            self.p = Popen([self.cmd], stdout=PIPE, bufsize=1,
                           universal_newlines=True, shell=True, executable='/bin/bash', preexec_fn=os.setsid)
        if not self.readThread:
            self.readThread = CommandWatch.Enqueue(self.p.stdout, self.q)

        self.readThread.start()
        count = 0
        t_end = time.time() + timer
        start_time = time.time()
        started = False
        while (timer == 0 or time.time() < t_end) and count < self.countdown:
            try:
                line = self.q.get_nowait()
            except Empty:
                pass
            else:  # got line
                if not started:
                    if self.start_pattern and self.start_pattern.match(line):
                        start_time = time.time()
                        started = True
                        continue
                    else:
                        start_time = time.time()
                        started = True
                if self.end_pattern and self.end_pattern.match(line):
                    count += 1
        end_time = time.time()
        return end_time - start_time

if __name__ == "__main__":
    randomEchoWatch = CommandWatch(
        cmd='while true; do sleep 1; val=$RANDOM; if [[ $(( val % 2 )) -eq 0 ]]; then echo "Size of notification queue is: $val"; fi; done;',
        countdown=50,
        end_pattern=".*(Size of notification queue is:)\s*\d+\s*")
    future = randomEchoWatch.submit(10)
    print("Some task...")
    try:
        print("Time taken: "+str(future.result())+" s")
    except TimeoutError as err:
        print("Time out!")


