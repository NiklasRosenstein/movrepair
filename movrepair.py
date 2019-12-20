# The MIT License (MIT)
#
# Copyright (c) 2017 Niklas Rosenstein
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from __future__ import division, print_function
from movio import MovFileError, MovAtomR, MovAtomD, MovAtomW, get_file_size_via_seek
import movatoms
import argparse
import collections
import os
import struct
import sys


def guess_sequence_repitition_length(seq):
  # Thanks to https://stackoverflow.com/a/11385797/791713
  guess = 1
  max_len = len(seq) // 2
  for x in range(2, max_len):
    if seq[0:x] == seq[x:2*x] :
      return x
  return guess


def calc_item_delta(sequence):
  result = []
  for i in range(1, len(sequence)):
    result.append(sequence[i] - sequence[i-1])
  return result


def sizeof_fmt(num, suffix='B'):
  # Thanks to https://stackoverflow.com/a/1094933
  for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
    if abs(num) < 1024.0:
      return "%3.1f%s%s" % (num, unit, suffix)
    num /= 1024.0
  return "%.1f%s%s" % (num, 'Yi', suffix)


def fix_metadata(scale_factor, moov):
  """
  Attempts to update the metadata in the `moov` atom, scaling the duration
  and sample counts by the specified *scale_factor*.

  The following atom types will be updated:

  * mvhd
  * trak > tkhd
  * trak > edts > elst
  * trak > mdia > mdhd
  * trak > mdia > minf > {stts, stco, stsz}

  Any time-code track (with data_format `tmcd`) will be removed.
  """

  updated_atoms = []

  # Find a new duration for the new file based on the size of the reference
  # file's duration and sample size in bytes.
  def get_new_duration(atom):
    time_scale, ref_duration = struct.unpack('>II', atom.data[12:20])
    new_duration = int(scale_factor * ref_duration)
    print('Adjusting "{}" duration from {}s to {}s.'.format(
        atom.tag.decode('ascii', 'ignore'),
        ref_duration/time_scale,
        new_duration/time_scale))
    return ref_duration, new_duration
  mvhd = moov.find_atoms(b'mvhd')[0]
  ref_duration, new_duration = get_new_duration(mvhd)
  new_duration_packed = struct.pack('>I', new_duration)

  mvhd.edit()[16:20] = new_duration_packed
  updated_atoms.append(mvhd)
  for tkhd in moov.find_atoms(b'trak', b'tkhd'):
    updated_atoms.append(tkhd)
    tkhd.edit()[20:24] = new_duration_packed
  for elst in moov.find_atoms(b'trak', b'edts', b'elst'):
    updated_atoms.append(elst)
    # NOTE: There could be multiple entries in the reference file or in the
    #       broken file. The former we don't care about, but the latter we
    #       can't know. We'll just assume one entry.
    flag = struct.unpack('>I', elst.data[:4])[0]
    rate = struct.unpack('>I', elst.data[16:20])[0]
    values = [flag, 1, new_duration, 0, rate]
    elst.edit()[:] = struct.pack('>IIIII', *values)
  for mdhd in moov.find_atoms(b'trak', b'mdia', b'mdhd'):
    updated_atoms.append(mdhd)
    mdhd_dur = get_new_duration(mdhd)[1]
    mdhd.edit()[16:20] = struct.pack('>I', mdhd_dur)

  # Adjust the sample information for the changed duration and sample count.
  for minf in moov.find_atoms(b'trak', b'mdia', b'minf'):
    vmhd = next(iter(minf.find_atoms(b'vmhd')), None)
    for stbl in minf.find_atoms(b'stbl'):

      # Sample description atom
      desc_atom = stbl.find_atoms(b'stsd')[0]
      desc = movatoms.stsd.unpack(desc_atom.data)
      data_format = desc.descriptions[0].data_format

      if data_format == b'tmcd':
        print('Removing tmcd track')
        assert minf.parent.parent.tag == b'trak'
        moov.atoms.remove(minf.parent.parent)

      # Time-to-sample atom
      stts_atom = stbl.find_atoms(b'stts')[0]
      stts = movatoms.stts.unpack(stts_atom.data)
      if data_format != b'tmcd':
        table = []
        for nsamples, sample_duration in stts.table:
          nsamples_new = int(nsamples * scale_factor)
          print('Adjusting sample count from {} to {}'.format(nsamples, nsamples_new))
          table.append((nsamples_new, sample_duration))
        stts_atom.data = stts.pack()
        updated_atoms.append(stts_atom)

      # Chunk Offset atom
      stco_atom = stbl.find_atoms(b'stco')[0]
      stco = movatoms.stco.unpack(stco_atom.data)
      if len(stco.table) > 1:
        print('Extending {} chunk offset table'.format(data_format))
        count = int(len(stco.table) * scale_factor)
        deltas = calc_item_delta(stco.table)
        repn = guess_sequence_repitition_length(deltas)
        offset = len(deltas) % repn
        for i in range(count-len(stco.table)):
          delta = deltas[offset+(i%repn)]
          stco.table.append(stco.table[-1]+delta)
        stco_atom.data = stco.pack()
        updated_atoms.append(stco_atom)

      # Sample Size atom
      stsz_atom = stbl.find_atoms(b'stsz')[0]
      stsz = movatoms.stsz.unpack(stsz_atom.data)
      if len(stsz.table) > 1:
        count = int(len(stsz.table) * scale_factor)
        deltas = calc_item_delta(stsz.table)
        repn = guess_sequence_repitition_length(deltas)
        print('Extending {} sample size table (table size: {}, guesssed repartition length: {})'
              .format(data_format, repn))
        offset = len(deltas) % repn
        for i in range(count-len(stsz.table)):
          delta = deltas[offset+(i%repn)]
          stsz.table.append(stsz.table[-1]+delta)
        stsz_atom.data = stsz.pack()
        updated_atoms.append(stsz_atom)

  print('Updated moov atoms:', ', '.join(x.tag.decode('ascii', 'ignore') for x in updated_atoms))


def repair_file(reference, broken, output, do_fix_metadata=True):
  """
  Tries to repair the *broken* file using the *reference* file and writes it
  to the *output* file. This function will transfer all sections from the
  *reference* file to the *output* file, except for the `mdat` atom which is
  taken from the *broken* file instead.

  We assume the order of atoms in the reference file is the same as the
  order of atoms in the broken input file.
  """

  # Extract the meta information atoms from the reference file.
  reference_atoms = collections.OrderedDict()
  end_file_offset = 0
  for atom in MovAtomR.make_root(reference).iter_atoms():
    if atom.tag != b'mdat':
      # We keep track of the number of bytes used in the reference file for
      # atoms after the mdat atom.
      if b'mdat' in reference_atoms:
        end_file_offset += atom.size

      # Read in the full contents of this atom into memory.
      atom = atom.to_atomd()

      # Ensure that we have the moov atom after the mdat atom. We need
      # this for later as we need to update it after we write the broken
      # file's mdat.
      if b'moov' in reference_atoms:
        reference_atoms[b'moov'] = reference_atoms.pop(b'moov')

    reference_atoms[atom.tag] = atom

  # Find the `mdat` atom in the broken input file. Do NOT read it so we
  # can stream its contents to the output file later.
  for atom in MovAtomR.make_root(broken).iter_atoms():
    if atom.tag == b'mdat':
      mdat = atom
      break
  else:
    print('error: could not find mdat atom in broken input file')
    return 1

  # We assume that the header of the mdat is broken and we need to adjust
  # for the atoms after the mdat section (#end_file_offset).
  mdat_size = get_file_size_via_seek(mdat.file) - mdat.atom_begin# - end_file_offset
  print('Broken file\'s mdat size adjusted from {} to {}'.format(
      sizeof_fmt(mdat.size), sizeof_fmt(mdat_size)))
  mdat.size = mdat_size

  # Update the duration and sample counts in the metadata.
  if do_fix_metadata:
    scale_factor = mdat.size / float(reference_atoms[b'mdat'].size)
    print('Scale factor to fix metadata:', scale_factor)
    fix_metadata(scale_factor, reference_atoms[b'moov'])

  # Write the reference file's atoms and the mdat from the broken file.
  for atom in reference_atoms.values():
    if atom.tag == b'mdat':
      with MovAtomW(output, mdat_size, atom.tag) as writer:
        for chunk in mdat.iter_data(1024):
          writer.write(chunk)
    else:
      atom.write(output)
  return 0


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('file', help='A working video file. If no additional '
    'options are specified, the to-level atoms of this file will be displayed.')
  parser.add_argument('-o', '--output', help='The repaired output filename.')
  parser.add_argument('-R', '--repair',
    help='A file to repair using the working input file.')
  parser.add_argument('--no-fix-metadata', action='store_true',
    help='Don\'t try to fix the `moov` atom metadata duration and sample '
      'counts. This will require the input FILE to be the same length or '
      'longer than the REPAIR file.')
  parser.add_argument('--dump-moov', action='store_true',
    help='Dump the input FILE\'s `moov` atom to stdout.')
  args = parser.parse_args()

  if args.dump_moov:
    with open(args.file, 'rb') as fp:
      for atom in MovAtomR.make_root(fp).iter_atoms():
        if atom.tag == b'moov':
          moov = movatoms.moov.unpack(atom.read_data())
    moov.pretty_print()
  elif args.repair:
    if not args.output:
      name, ext = os.path.splitext(args.repair)
      args.output = name + '-fixed' + ext
    print('Output file:', args.output)
    with open(args.file, 'rb') as reference, \
        open(args.repair, 'rb') as broken, \
        open(args.output, 'wb') as output:
      return repair_file(reference, broken, output, do_fix_metadata=not args.no_fix_metadata)
  else:
    with open(args.file, 'rb') as fp:
      print('file size:', sizeof_fmt(get_file_size_via_seek(fp)))
      for atom in MovAtomR.make_root(fp).iter_atoms():
        print('* {} ({})'.format(atom.tag.decode('ascii', 'ignore'), sizeof_fmt(atom.size)))
    return 0


if __name__ == '__main__':
  sys.exit(main())
