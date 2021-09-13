#!/usr/bin/env python3
# Updates from LorenzoG 
# 2021 - ZephrFish Added colours functions

"""
DNS Parallel Prober
===================

Given a domain name, probes its subdomains either by brute-force or from a list.

See `README.md` for more information and usage.

"""

from __future__ import print_function
import argparse
from collections import deque
import itertools
import logging
import os
import random
import progressbar
import socket
import string
import sys
import time
import threading
try:
    import dns.query
    import dns.resolver
except ImportError:
    # pip install dnspython
    raise SystemExit("Module 'dnspython' not found. Are you in the virtualenv? "
                     "See README.md for quickstart instructions.")

INCREASE_PERCENT = 0.1
DEFAULT_MAX_SUBDOMAIN_LEN = 3
DEFAULT_DNS_TIMEOUT = 5
# for checking whether the DNS is a wildcard DNS...
RANDOM_SUBDOMAINS = 5
RANDOM_SUBDOMAINS_LENGTH = 6

# Colours
def prRed(skk): print("\033[91m {}\033[00m" .format(skk))
def prGreen(skk): print("\033[92m {}\033[00m" .format(skk))
def prCyan(skk): print("\033[96m {}\033[00m" .format(skk))
def prYellow(skk): print("\033[93m {}\033[00m" .format(skk))

# valid domain names allow ASCII letters, digits and hyphen (and are case
# insensitive)
# however see
# http://stackoverflow.com/questions/7111881/what-are-the-allowed-characters-in-a-sub-domain
# and https://en.wikipedia.org/wiki/Domain_name#Internationalized_domain_names
ALPHABET = ''.join([
    string.ascii_lowercase,
    string.digits,
    # technically domains shouldn't start or end with a -
    '-',
    # add here unicode characters sets
])

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
sh.setFormatter(logging.Formatter())
log.addHandler(sh)
log.setLevel(logging.INFO)


# global object to collect results
res = deque()
# and errors
err = deque()


class RealProber(threading.Thread):
    def __init__(self, dns_server, target, dns_timeout, results_collector, error_collector):
        # invoke Thread.__init__
        super(RealProber, self).__init__()
        self.target = target
        self.dns_server = dns_server
        self.dns_timeout = dns_timeout
        # used for storing the results
        if results_collector is None:
            # use the global object
            self.res = res
        else:
            # used to save the output in a temporary object
            self.res = results_collector

        if error_collector is None:
            self.err = err
        else:
            self.err = error_collector

    def run(self):
        resolver = dns.resolver.Resolver()
        resolver.timeout = self.dns_timeout
        # as per http://comments.gmane.org/gmane.comp.python.dnspython.user/144
        resolver.lifetime = self.dns_timeout
        try:
            log.debug("{}: Resolving {} with nameserver {}".format(
                self.name, self.target, self.dns_server))
            # it's a list
            resolver.nameservers = [self.dns_server, ]
            answer = resolver.query(self.target)
            for data in answer:
                out = '{} | {}'.format(self.target, data)
                self.res.append(out)
                # don't log to console, use file.
                # log.info(out)
        except dns.exception.Timeout as e:
            # we want to know if the DNS server is barfing
            errmsg = "{}: {}".format(self.target, e)
            self.err.append(errmsg)
            # log.warn(errmsg)
        except dns.exception.DNSException as e:
            log.debug("Error in thread {} when querying {}: {}".format(
                self.name, self.target, e))


class MockProber(RealProber):
    def __init__(self, *args, **kwargs):
        super(MockProber, self).__init__(*args, **kwargs)
        log.debug("Mock prober {} initialised with {} {}".format(self.name, *args, **kwargs))

    def run(self):
        # sleep for a small amount of time, between 0.1 and 0.9
        _sleep_for = abs(random.normalvariate(0.5, 0.5))
        log.debug("Mock probe {} sleeping for {}...".format(self.name, _sleep_for))
        time.sleep(_sleep_for)
        if random.random() > 0.7:
            log.debug("Mock probe {} found a result.")
            res.append("{} | {}".format(self.target, '127.0.0.1'))
        log.debug("Mock prober {} done".format(self.name))


class LoggingThread(threading.Thread):
    """Takes care of writing to disk as new hosts are discovered"""
    def __init__(self, log_event, outfile):
        super(LoggingThread, self).__init__()
        self.log_event = log_event
        self.outfile = None
        if outfile is not None:
            prGreen("[+] Saving results to {}...".format(outfile))
            self.outfile = open(outfile, 'w')
        self.running = True

    def run(self):
        # old code
        # if outfile is not None:
        #     print("[+] Saving {} results to {}...".format(len(res), outfile))
        #     with open(outfile, 'w') as f:
        #         for r in res:
        #             f.write('{}\n'.format(r))
        # else:
        #     print('\n'.join(res))
        if self.outfile is None:
            log.debug("Nothing to do for the logging thread...")
            return

        while self.running:
            self.log_event.wait()
            while len(res) > 0:
                _el = res.popleft()
                self.outfile.write('{}\n'.format(_el))
                # print('{}'.format(_el))
            self.outfile.flush()

        self.outfile.close()


def random_subdomain():
    """A generator that returns random subdomains, used for checking
    wildcard DNS"""
    for i in range(RANDOM_SUBDOMAINS):
        _random_subdomain = ''
        for j in range(RANDOM_SUBDOMAINS_LENGTH):
            _random_subdomain += random.choice(ALPHABET)
        yield _random_subdomain


def subdomain_gen(max_subdomain_len):
    """A generator that.. generates all permutations of subdomains from the given alphabet"""
    for i in range(max_subdomain_len):
        for p in itertools.permutations(ALPHABET, i + 1):
            yield ''.join(p)


def subdomain_len(max_subdomain_len):
    import math
    total = 0
    for i in range(max_subdomain_len):
        total += math.factorial(len(ALPHABET)) / math.factorial(len(ALPHABET) - i - 1)
    return total


def subdomain_fromlist(the_list):
    # XXX this could be optimised by reading chunks from the file to avoid
    # disk access every new subdomain, but if network access is slower than
    # disk access then we should be OK.
    """A generator that returns the content from a file without loading it all in memory"""
    with open(the_list) as f:
        for line in f.readlines():
            yield line.replace('\n', '')


def subdomain_fromlist_len(the_list):
    with open(the_list) as f:
        return len(f.readlines())


# fills the queue with new threads
# XXX IMPORTANT -- When this function is used to check for wildcard DNSs then
# 'amount' must be at least as big as the number of subdomains, otherwise the
# remaining will be left out. Reason: there's no replenishing of the queue when
# doing wildcard dns checks.
def fill(d, amount, dom, sub, nsvrs, dns_timeout, results_collector=None, error_collector=None):
    for i in range(amount):
        # calls next() on the generator to get the next target
        _target = '{}.{}'.format(next(sub), dom)
        t = Prober(
            # pick a dns server
            random.choice(nsvrs),
            _target,
            dns_timeout,
            results_collector,
            error_collector)
        t.start()
        d.append(t)


def do_check_wildcard_dns(dom, nsvrs, dns_timeout):
    prGreen("[+] Checking wildcard DNS...")
    # a wildcard DNS returns the same IP for every possible query of a
    # non-existing domain
    wildcard_checklist = deque()
    wildcard_results = deque()
    wildcard_error = deque()
    try:
        # XXX the second parameter must be at least as big as the number of
        # random subdomains; as there's no replenishing of the queue here, if
        # it's less than RANDOM_SUBDOMAINS then some will be left out.
        fill(
            wildcard_checklist,
            RANDOM_SUBDOMAINS,
            dom,
            random_subdomain(),
            nsvrs,
            dns_timeout,
            wildcard_results,
            wildcard_error)
        # wait for the probes to finish
        for el in range(len(wildcard_checklist)):
            t = wildcard_checklist.popleft()
            t.join()
    except KeyboardInterrupt as e:
        raise SystemExit(e)

    # print errors, if any
    if len(wildcard_error) > 0:
        log.warn('\n'.join(wildcard_error))
        prRed('\n'.join(wildcard_error))

    # TODO: parse results, stop if they all have a positive hit
    # for now we simply count the number of hits
    if len(wildcard_results) == RANDOM_SUBDOMAINS:
        raise SystemExit(
            "{} random subdomains returned a hit; "
            "It is likely this is a wildcard DNS server. "
            "Use the -w option to skip this check.".format(
                RANDOM_SUBDOMAINS))


def main(dom,
         max_running_threads,
         outfile,
         overwrite,
         infile,
         use_nameserver,
         max_subdomain_len,
         dns_timeout,
         no_check_wildcard_dns,
         errfile=None):

    #
    ###
    # output management
    #
    print("[+] Output destination: '{}'".format(outfile))
    if outfile is not None and os.path.exists(outfile):
        if overwrite is False:
            raise SystemExit(
                "Specified file '{}' exists and overwrite "
                "option (-f) not set".format(outfile))
        else:
            prRed("[+] Output destination will be overwritten.")
    # print(
    #     "-: queue ckeck interval increased by {}%\n.: "
    #     "no change\n".format(INCREASE_PERCENT))

    #
    ###
    #

    prCyan("[+] Press CTRL-C to gracefully stop...")

    #
    ###
    # finding DNS servers
    #

    nsvrs = list()
    if use_nameserver:
        prCyan("[+] Using user-supplied name servers...")
        _nsvrs = use_nameserver
    else:
        try:
            prCyan("[+] Finding authoritative name servers for domain...")
            _nsvrs = dns.resolver.query(args.domain, 'NS')
        except dns.exception as e:
            raise SystemExit(e)
        except KeyboardInterrupt as e:
            raise SystemExit(e)
    for ns in _nsvrs:
        log.debug('ns: {}'.format(ns))
        try:
            nsvrs.append(socket.gethostbyname(str(ns)))
        except socket.gaierror as e:
            log.error("[ ] Error when resolving {}: {}".format(ns, e))
    if len(nsvrs) == 0:
        raise RuntimeError("None of the supplied name servers resolve to a valid IP")
    prCyan('[+] Using name servers: {}'.format(nsvrs))

    #
    ###
    # check for wildcard DNS
    #

    # hate double negatives
    check_wildcard_dns = not no_check_wildcard_dns
    if check_wildcard_dns:
        do_check_wildcard_dns(dom, nsvrs, dns_timeout)

    #
    ###
    # Begin

    # this is the starting value - it will adjust it according to depletion
    # rate
    sleep_time = 0.5

    # the main queue containing all threads
    d = deque()

    if infile is None:
        # use the inbuilt subdomain generator
        sub = subdomain_gen(max_subdomain_len)
        total_domains = subdomain_len(max_subdomain_len)
        prGreen("[+] Will search for subdomains made of all possible {}-characters permutations".format(max_subdomain_len))
    else:
        if not os.path.exists(infile):
            raise SystemExit("{} not found".format(infile))
        sub = subdomain_fromlist(infile)
        total_domains = subdomain_fromlist_len(infile)
        prGreen("[+] Will search for subdomains contained in '{}'".format(infile))

    # trigger for logging; set every iteration loop, wait()ed for 
    # in the logging thread
    log_event = threading.Event()
    logging_thread = LoggingThread(log_event, outfile)
    logging_thread.start()

    # pre-loading of queue
    print("[+] DNS probing starting...")
    log.debug("Progressbar initialised with {} max".format(total_domains))
    # NOTE if python complains max_value is not found, you've installed
    # "progressbar" and not "progressbar2"
    bar = progressbar.ProgressBar(max_value=total_domains)
    try:
        # fill the queue ip to max for now
        #    nsvrs = dns.resolver.query(dom, 'NS')
        # ns = str(nsvrs[random.randint(0, len(nsvrs)-1)])[:-1]
        fill(d, max_running_threads, dom, sub, nsvrs, dns_timeout)
        running = True
    except StopIteration:
        running = False
    except KeyboardInterrupt:
        running = False

    done = 0
    previous_len = len(d)
    while running:
        try:
            time.sleep(sleep_time)
            # go through the queue and remove the threads that are done
            for el in range(len(d)):
                _t = d.popleft()
                if _t.is_alive():
                    # put it back in the queue until next iteration
                    d.append(_t)

            # calculate how fast the queue has been changing
            delta = previous_len - len(d)
            rate = delta / sleep_time
            # print('\tq: {}\tdelta: {}\trate: {}\t{}s'.format(
            #     len(d), delta, rate, sleep_time))
            done += delta
            bar.update(done)

            if rate > 0 and delta > max_running_threads / 10:
                sleep_time -= (sleep_time * INCREASE_PERCENT)
                # print('+', end="")
            else:
                sleep_time += (sleep_time * INCREASE_PERCENT)
                # print('.', end="")

            fill(d, delta, dom, sub, nsvrs, dns_timeout)
            previous_len = len(d)

            # wakeup the logging thread for disk and output
            log_event.set()

        except KeyboardInterrupt:
            prCyan("\n[+] DNS probing stopped.")
            running = False
        except StopIteration:
            bar.finish()
            prGreen("\n[+] DNS probing done.")
            running = False
        finally:
            sys.stdout.flush()

    prYellow("[+] Waiting for all threads to finish...")
    # waiting for all threads to finish, popping them one by one and join()
    # each...
    for el in range(len(d)):
        t = d.popleft()
        t.join()

    # wake up and kill the logging thread
    # it should be stuck in the wait() loop..
    logging_thread.running = False
    # write the last results
    log_event.set()

    if errfile is not None:
        # default: overwrites error file
        with open(errfile, 'w') as f:
            f.write('\n'.join(err))
    else:
        log.warn('\n'.join(err))

    print("[+] Done.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("domain")
    parser.add_argument(
        "max_running_threads",
        type=int,
        help=(
            "Maximum number of threads to run. Most will be idle "
            "waiting for network timeout, so start around 100 and "
            "keep doubling until it looks too big."
        )
    )
    parser.add_argument("savefile", default="out.txt")
    parser.add_argument(
        "-e",
        '--error-file',
        default=None,
        help="File to collect error messages. Will be overwritten"
    )
    parser.add_argument(
        "-f", "--force-overwrite", default=False,
        action='store_true')
    parser.add_argument(
        "-i", "--use-list", help="Reads the list from a file",
        default=None)
    parser.add_argument(
        "-l",
        "--max-subdomain-len",
        type=int,
        default=DEFAULT_MAX_SUBDOMAIN_LEN,
        help=(
            "Maximum length of the subdomain for bruteforcing. "
            "Default: {}".format(DEFAULT_MAX_SUBDOMAIN_LEN)
        )
    )
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument(
        '-n',
        '--use-nameserver',
        action='append',
        help=("Use this DNS server. Can be repeated multiple "
              "times and a random one will be picked each time")
    )
    parser.add_argument(
        '-t',
        '--dns-timeout',
        default=DEFAULT_DNS_TIMEOUT,
        help="How long to wait for a DNS response. Default: {}s".format(DEFAULT_DNS_TIMEOUT)
    )
    parser.add_argument(
        '-w',
        '--no-check-wildcard-dns',
        action='store_true',
        default=False,
        help="Skip the check for wildcard DNS"
    )
    parser.add_argument(
        '--simulate',
        action='store_true',
        help="Simulate the probing with random timeouts"
    )

    args = parser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)
        log.debug("Debug logging enabled")

    global Prober
    if args.simulate:
        Prober = MockProber
        prRed('[*] SIMULATION IN PROGRESS')
    else:
        Prober = RealProber

    main(
        args.domain,
        args.max_running_threads,
        args.savefile,
        args.force_overwrite,
        args.use_list,
        args.use_nameserver,
        args.max_subdomain_len,
        args.dns_timeout,
        args.no_check_wildcard_dns,
        args.error_file,
    )
