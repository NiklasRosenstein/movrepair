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
import movfile
import argparse
import collections
import json
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


def repair_file(reference, broken, output):
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

  # TESTING
  moov = movfile.moov.unpack(reference_atoms[b'moov'].data)
  print(moov)
  return

  # Find a new duration for the new file based on the size of the reference
  # file's duration and sample size in bytes.
  def get_new_duration(atom):
    time_scale, ref_duration = struct.unpack('>II', atom.data[12:20])
    new_duration = int(mdat.size / reference_atoms[b'mdat'].size * ref_duration)
    print('Adjusting "{}" duration from {}s to {}s.'.format(
        atom.tag.decode('ascii', 'ignore'),
        ref_duration/time_scale,
        new_duration/time_scale))
    return ref_duration, new_duration
  moov = reference_atoms[b'moov']
  mvhd = moov.find_atoms(b'mvhd')[0]
  ref_duration, new_duration = get_new_duration(mvhd)
  new_duration_packed = struct.pack('>I', new_duration)

  updated_atoms = []
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
  scale_factor = new_duration / ref_duration
  for minf in moov.find_atoms(b'trak', b'mdia', b'minf'):
    vmhd = next(iter(minf.find_atoms(b'vmhd')), None)
    for stbl in minf.find_atoms(b'stbl'):

      # Sample description atom
      desc_atom = stbl.find_atoms(b'stsd')[0]
      desc = movfile.stsd.unpack(desc_atom.data)

      if desc.desc[0].fmt == b'tmcd':
        print('Removing tmcd track')
        assert minf.parent.parent.tag == b'trak'
        moov.atoms.remove(minf.parent.parent)

      # Time-to-sample atom
      stts_atom = stbl.find_atoms(b'stts')[0]
      stts = movfile.stts.unpack(stts_atom.data)
      if desc.desc[0].fmt != b'tmcd':
        table = []
        for nsamples, sample_duration in stts.table:
          nsamples_new = int(nsamples * scale_factor)
          print('Adjusting sample count from {} to {}'.format(nsamples, nsamples_new))
          table.append((nsamples_new, sample_duration))
        stts_atom.data = stts.pack()
        updated_atoms.append(stts_atom)

      # Sync Sample atom
      #stss_atom = stbl.find_atoms(b'stss')[0]
      #stss = StssAtom.unpack(stss_atom.data)

      # Sample-to-chunk atom
      stsc_atom = stbl.find_atoms(b'stsc')[0]
      stsc = movfile.stsc.unpack(stsc_atom.data)

      # Chunk Offset atom
      stco_atom = stbl.find_atoms(b'stco')[0]
      stco = movfile.stco.unpack(stco_atom.data)
      if len(stco.table) > 1:
        print('Extending {} chunk offset table'.format(desc.desc[0].fmt))
        count = int(len(stco.table) * scale_factor)
        deltas = calc_item_delta(stco.table)
        repn = guess_sequence_repitition_length(deltas)
        offset = len(deltas) % repn
        for i in range(count-len(stco.table)):
          delta = deltas[offset+(i%repn)]
          stco.table.append(stco.table[-1]+delta)
        updated_atoms.append(stco_atom)

      # Sample Size atom
      stsz_atom = stbl.find_atoms(b'stsz')[0]
      stsz = movfile.stsz.unpack(stsz_atom.data)
      if len(stsz.table) > 1:
        print('Extending {} sample size table'.format(desc.desc[0].fmt))
        count = int(len(stsz.table) * scale_factor)
        print('stsz count:', count)
        deltas = calc_item_delta(stsz.table)
        repn = guess_sequence_repitition_length(deltas)
        offset = len(deltas) % repn
        for i in range(count-len(stsz.table)):
          delta = deltas[offset+(i%repn)]
          stsz.table.append(stsz.table[-1]+delta)
        stsz_atom.data = stsz.pack()
        updated_atoms.append(stsz_atom)

  print('Updated moov atoms:', ', '.join(x.tag.decode('ascii', 'ignore') for x in updated_atoms))
  #return


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
  parser.add_argument('file')
  parser.add_argument('-o', '--output', help='The repaired output file.')
  parser.add_argument('-R', '--repair', help='A file to repair using the input file.')
  parser.add_argument('--dump-moov', help='Specify an output file for the .moov atom dump.')
  args = parser.parse_args()



  if args.repair:
    if not args.output:
      name, ext = os.path.splitext(args.repair)
      args.output = name + '-fixed' + ext
    print('Output file:', args.output)
    with open(args.file, 'rb') as reference, \
        open(args.repair, 'rb') as broken, \
        open(args.output, 'wb') as output:
      return repair_file(reference, broken, output)
  elif args.dump_moov:
    def transform(node):
      if isinstance(node, tuple) and type(node).__name__ in vars(movfile):
        node = transform({'type': type(node).__name__, 'data': node._asdict()})
      elif isinstance(node, list):
        node = [transform(x) for x in node]
      elif isinstance(node, dict):
        node = {transform(k): transform(v) for k, v in node.items()}
      return node

    class Encoder(json.JSONEncoder):
      def default(self, obj):
        if isinstance(obj, bytes):
          return repr(obj)
        return json.JSONEncoder.default(self, obj)

    with open(args.file, 'rb') as fp:
      for atom in MovAtomR.make_root(fp).iter_atoms():
        if atom.tag == b'moov':
          moov = movfile.moov.unpack(atom.read_data())

    with open(args.dump_moov, 'w') as fp:
      json.dump(transform(moov), fp, indent=2, cls=Encoder)

  else:
    with open(args.file, 'rb') as fp:
      print('file size:', sizeof_fmt(get_file_size_via_seek(fp)))
      for atom in MovAtomR.make_root(fp).iter_atoms():
        print('* {} ({})'.format(atom.tag.decode('ascii', 'ignore'), sizeof_fmt(atom.size)))
    return 0


if __name__ == '__main__':
  sys.exit(main())
