import sys

from .engine import actor, work

if __name__ == "__main__":
    if len(sys.argv) > 2:
        actor.set(sys.argv[2])
    work(sys.argv[1])
