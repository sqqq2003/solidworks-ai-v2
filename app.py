"""SolidWorks AI desktop entry. Importing never creates a window."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def main():
    from desktop_ui import run
    run()


if __name__=='__main__':main()
