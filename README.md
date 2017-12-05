## movrepair

Movrepair is a script that attempts to repair a broken `.mov` file. In my
specific use-case, the size-header of the `mdat` atom was broken, also leading
to the destruction of following atoms.

This script will take a *working* reference video file and copy all atoms
except for the `mdat` atom, which will be used from the broken input file.

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
    Adjusting "mvhd" duration from 4.5045s to 13.540166666666666s.
    Adjusting "mdhd" duration from 4.5045s to 13.540166666666666s.
    Adjusting "mdhd" duration from 4.5045s to 13.540166666666666s.
    Adjusting "mdhd" duration from 4.5045s to 13.540166666666666s.
    Adjusting sample count from 216216 to 649928
    Extending b'in24' chunk offset table
    Adjusting sample count from 135 to 405
    Extending b'AVdh' chunk offset table
    Extending b'AVdh' sample size table
    stsz count: 405
    Removing tmcd track
    Updated moov atoms: mvhd, tkhd, tkhd, tkhd, elst, elst, elst, mdhd, mdhd, mdhd, stts, stco, stts, stco, stsz

If the "repaired" file still does not work, try using a video file that is
at least as long as the file you're trying to repair and pass the
`--no-fix-metadata` option.

    $ python movrepair.py reference.MOV --repair 0A3C0B00.MOV --no-fix-metadata
    Output file: 0A3C0B00-fixed.MOV
    Broken file's mdat size adjusted from 1.4GiB to 297.5MiB

__Disclaimer__: Use at your own risk.

### Synopsis

```
usage: movrepair.py [-h] [-o OUTPUT] [-R REPAIR] [--no-fix-metadata]
                    [--dump-moov]
                    file

positional arguments:
  file                  A working video file. If no additional options are
                        specified, the to-level atoms of this file will be
                        displayed.

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        The repaired output filename.
  -R REPAIR, --repair REPAIR
                        A file to repair using the working input file.
  --no-fix-metadata     Don't try to fix the `moov` atom metadata duration and
                        sample counts. This will require the input FILE to be
                        the same length or longer than the REPAIR file.
  --dump-moov           Dump the input FILE's `moov` atom to stdout.
```
