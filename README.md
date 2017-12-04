## movrepair

Movrepair is a script that attempts to repair a broken `.mov` file. In my
specific use-case, the size-header of the `mdat` atom was broken, also leading
to the destruction of following atoms.

This script will take a *working* reference video file and copy all atoms
except for the `mdat` atom, which will be used from the broken input file.
The duration in `moov` atom from the reference file will be adjusted based
on an estimate using the size of the `mdat` atom.

### Usage

To show the atoms of a (here broken) file:

    $ python movrepair.py 0A3C0B00.MOV
    file size: 297.5MiB
    * ftyp (24.0B)
    * wide (0.0B)
    * mdat (1.4GiB)

Attempt to repair the file:

    $ python movrepair.py reference.MOV --repair 0A3C0B00.MOV
    Output file: 0A3C0B00-fixed.MOV
    Broken file's mdat size adjusted from 1.4GiB to 297.5MiB
    Adjusting "mvhd" duration from 4.5045s to 13.5400666667s.
    Adjusting "mdhd" duration from 4.5045s to 13.5400625s.
    Adjusting "mdhd" duration from 4.5045s to 13.5400666667s.
    Adjusting "mdhd" duration from 4.5045s to 13.5400666667s.
    Updated moov atoms: mvhd, tkhd, tkhd, tkhd, elst, elst, elst, mdhd, mdhd, mdhd

__Disclaimer__: Use at your own risk.
