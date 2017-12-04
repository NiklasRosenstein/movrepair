## movrepair

I used this script to repair broken `.mov` files. You can use this script to
examine the atoms of a QuickTime `.mov` file or immediately attempt to repair
it. The repair-process is very straight forward and is not garuanteed to work
in your case, too.

You'll need a working reference `.mov` file recorded with the same camcorder.
Run the script on the working file to see a list of the top-level atoms.

    $ python movrepair.py SHOGUN_S017_S001_T001.MOV -h
    total file size: 99.0MiB
    * ftyp (24.0B)
    * wide (0.0B)
    * mdat (99.0MiB)
    * moov (2.4KiB)
    * free (52.0B)

Now, run the same script on the broken video file:

    $ python movrepair.py 0A3C0B00.MOV -h
    total file size: 297.5MiB
    * ftyp (24.0B)
    * wide (0.0B)
    * mdat (1.4GiB) [error: could only read 297.5MiB]

As you can already see, the size information of the `mdat` header seems to be
broken and we're missing the `moov` section which is mandatory.

To fix the file, run the following command:

    $ python movrepair.py SHOGUN_S017_S001_T001.MOV --repair 0A3C0B00.MOV
    Output file: 0A3C0B00-fixed.MOV
    Writing begin atoms from working reference file ...
    * ftyp
    * wide
    Size of atoms following mdat in reference file: 2544
    Looking for mdat section of broken file ...
    Writing mdat of broken file ...
    Writing end atoms from working reference file ...
    * moov
    * free
    Done.

__Important__ The repair-process simply takes the input file and replaces its
`mdat` with the `mdat` atom of the broken file, after the bytes for the
sections following `mdat` are stripped.

Use at your own risk.
