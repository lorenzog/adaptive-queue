DNS Queue - A Parallelised DNS Prober
=================================

This script is a proof of concept for a parallelised domain name prober. It creates a queue of threads and tasks each one to probe a sub-domain of the given root domain. At every iteration step each dead thread is removed and the queue is replenished as necessary.

**PLEASE NOTE** this script probes DNS servers actively, so please use at your own risk. You are likely to get blacklisted and/or saturate your bandwidth. Whatever you do, it's your responsibility to make sure you have approval for it.

Hat tip to: [Kyle F.](https://github.com/radman404) for the original idea.

![Demo Screenshot](screenshot.png?raw=true "Usage example")

### Installation
    git clone https://github.com/lorenzog/dns-parallel-prober.git
    cd dns-parallel-prober
    sudo apt-get install python-virtualenv python-pip
    virtualenv venv
    source venv/bin/activate
    pip install dnspython

### Quickstart

Scan `example.com` using 100 threads, save the result in `out.txt`:

    ./dns-queue.py example.com 100 out.txt

If you want to read the subdomains from a list, do:

    ./dns-queue.py example.com 100 out.txt -i subdomains.txt

For help:

    ./dns-queue.py -h


Press `ctrl-c` to stop - it will wait for the last threads to finish and only then write all results to `out.txt`.

### Demo Video
[![asciicast](https://asciinema.org/a/16teprhj9hykzrl8hmtyrte2k.png)](https://asciinema.org/a/16teprhj9hykzrl8hmtyrte2k)

### Notes

The key thing is that the iteration frequency is dynamically adapted to the depletion speed, i.e. the faster the threads complete the sooner new ones will be added until an equilibrium is reached. The tool tries to stay reasonably close to the maximum value set.

File `subdomains.txt` gathered from research carried out in 2014/15

More [stuff](http://haxpo.nl/haxpo2015ams/wp-content/uploads/sites/4/2015/04/D1-P.-Mason-K.-Flemming-A.-Gill-All-Your-Hostnames-Are-Belong-to-Us.pdf) to research.

### Why threads and not processes

Because in this scenario the bottleneck is the network, not the CPU. I'm happy to be proven wrong! Just fork this repo and submit a pull request and some empirical data to back your claim.

However, if you have *lots* of cores, perhaps a multi-process version might help -- or just launch this same program many times, feeding each process a different subdomain list. YMMV.



