from __future__ import print_function

import os, sys, termios
import struct
import itertools
from fcntl import ioctl

from collections import OrderedDict

class TerminfoError(Exception): pass

def encode_string_decorator(func):
    if sys.version_info[0] < 3:
        def inner(*args, **kwargs):
            return func(*args, **kwargs).encode(sys.stdout.encoding or 'utf-8')
        return inner
    else:
        return func

class Capability(object): 
    def __init__(self, variable, capname='', tcap_code='', description='', value=None):
        self.variable = variable
        self.capname = capname
        self.tcap_code = tcap_code
        self.description = description
        self.value = value
   
    @encode_string_decorator
    def __repr__(self):
        return u'<%s %s %s>' % (self.__class__.__name__, 
                                self.capname,
                                self.value.replace(u'\x1b', u'^')
                                          .replace(u'\x9b', u'^[')
                               )

class BooleanCapability(Capability): pass
class NumberCapability(Capability): pass
class StringCapability(Capability): pass

class UnknownCapability(Capability): 
    def __init__(self, *args):
        super(UnknownCapability, self).__init__('unknown')

class Terminfo(object):
    def __init__(self, name, aliases=None):
        self.name = name
        self.aliases = [name] + (aliases or [])
        self.longname = self.aliases[-1]
        self.booleans = OrderedDict()
        self.numbers = OrderedDict()
        self.strings = OrderedDict()

        self._by_var = {}
        self._by_capname = {}
        self._by_tcap_code = {}
        self._by_escape_code = {}
    

    def _reset_index(self):
        for k,c in itertools.chain(self.booleans.items(), 
                                   self.numbers.items(),
                                   self.strings.items()):
            self._by_var[c.variable] = c
            self._by_capname[c.capname] = c
            self._by_tcap_code[c.tcap_code] = c
        
        for k,c in self.strings.items():
            self._by_escape_code[c.value] = c

    def get(self, name):
        """Get the escape code associated to name.
        `name` can be either a varialble_name, a capname or a tcap code
        See man terminfo(5) to see which names are available.
        
        If the name is not supported, None is returned.
        If the name isn't present in the database an exception is raised.
        """
        # `name` is most likely a capname, so we try that first
        for i in (self._by_capname, self._by_var, self._by_tcap_code):
            if i.get(name):
                return i.get(name)
        else:
            raise TerminfoError("'%s' is not a valid terminfo entry" % name)

    def detect(self, escape_code):
        import re

        """
        str_params = '%(%' + \
            r'|[-+*/m&\|cisl^=><AO!~]|p[1-9]|[Pg][a-zA-Z]' + \
            r'|((:?[-+# ])?([0-9]+(\.[0-9]+)?)?[doxXs])' + \
            r"|('c'|\{[0-9]+\})" + \
            r"|(\?.*?;)" + \
        ')'
        """

        cap = self._by_escape_code.get(escape_code, UnknownCapability())
        cap.value = escape_code

        """
        pattern = re.compile(str_params)
        simplified = pattern.sub('', escape_code)
        print(repr(simplified))
        """

        #return self._by_escape_code.get(escape_code)
        return cap

    def get_size(self):
        rows, cols, height, width = struct.unpack('HHHH',
            ioctl(sys.stdin.fileno(), 
                  termios.TIOCGWINSZ, 
                  struct.pack('HHHH', 0, 0, 0, 0)))
        return rows, cols

def load_terminfo(terminal_name=None, fallback='vt100'):
    """
    If the environment variable TERM is unset try with `fallback` if not empty.
    vt100 is a popular terminal supporting ANSI X3.64.
    """

    terminal_name = os.getenv('TERM')
    if not terminal_name:
        if not fallback:
            raise TerminfoError('Environment variable TERM is unset and no fallback was requested')
        else:
            terminal_name = fallback
   
    if os.getenv('TERMINFO'):
        # from man terminfo(5):
        #   if the environment variable TERMINFO is set, 
        #   only that directory is searched
        terminfo_locations = [os.getenv('TERMINFO')]
    else:
        terminfo_locations = [] # from most to least important

        if os.getenv('TERMINFO_DIRS'):
            for i in os.getenv('TERMINFO_DIRS').split(':'):
                # from man terminfo(5)
                #   An empty directory name is interpreted as /usr/share/terminfo.
                terminfo_locations.append(i or '/usr/share/terminfo')

        terminfo_locations += [
            os.path.expanduser('~/.terminfo'),
            '/etc/terminfo',
            '/usr/local/ncurses/share/terminfo',
            '/lib/terminfo',
            '/usr/share/terminfo'
        ]

        # remove duplicates preserving order
        terminfo_locations = list(OrderedDict.fromkeys(terminfo_locations))

    terminfo_path = None
    for dirpath in terminfo_locations:
        path = os.path.join(dirpath, terminal_name[0], terminal_name)
        if os.path.exists(path):
            terminfo_path = path
            break

    if not path:
        raise TerminfoError("Couldn't find a terminfo file for terminal '%s'" % terminal_name)

    from terminfo_index import BOOLEAN_CAPABILITIES, NUMBER_CAPABILITIES, STRING_CAPABILITIES

    data = open(terminfo_path, 'rb').read()

    # header (see man term(5), STORAGE FORMAT)
    header = struct.unpack('<hhhhhh', data[:12]) # 2 bytes == 1 short integer 
    magic_number  = header[0] # the magic number (octal 0432)
    size_names    = header[1] # the size, in bytes, of the names section
    size_booleans = header[2] # the number of bytes in the boolean section
    num_numbers   = header[3] # the number of short integers in the numbers section
    num_offsets   = header[4] # the number of offsets (short integers) in the strings section
    size_strings  = header[5] # the size, in bytes, of the string table

    if magic_number != 0o432:
        raise TerminfoError('Bad magic number')
 
    # sections indexes

    idx_section_names    = 12
    idx_section_booleans = idx_section_names + size_names
    idx_section_numbers  = idx_section_booleans + size_booleans

    if idx_section_numbers % 2 != 0:
        idx_section_numbers += 1 # must start on an even byte

    idx_section_strings  = idx_section_numbers + 2 * num_numbers
    idx_section_string_table = idx_section_strings + 2 * num_offsets

    # terminal names
    terminal_names = data[idx_section_names:idx_section_booleans].decode('ascii')
    terminal_names = terminal_names[:-1].split('|') # remove ASCII NUL and split

    terminfo = Terminfo(terminal_names[0], terminal_names[1:])

    # booleans
    for i, idx in enumerate(range(idx_section_booleans, idx_section_booleans + size_booleans)):
        cap = BooleanCapability(*BOOLEAN_CAPABILITIES[i], value=data[i] == b'\x00')
        terminfo.booleans[cap.variable] = cap

    # numbers
    numbers = struct.unpack('<'+'h' * num_numbers, data[idx_section_numbers:idx_section_strings])
    for i,strnum in enumerate(numbers):
        cap = NumberCapability(*NUMBER_CAPABILITIES[i], value=strnum)
        terminfo.numbers[cap.variable] = cap

    # strings
    offsets = struct.unpack('<'+'h' * num_offsets, data[idx_section_strings:idx_section_string_table])

    idx = 0
    for offset in offsets:
        k = 0
        string = []
        while True and offset != -1:
            char = data[idx_section_string_table + offset + k:idx_section_string_table + offset + k + 1]
            if char == b'\x00':
                break

            string.append(char.decode('iso-8859-1'))
            k += 1
        string = u''.join(string)
        
        cap = StringCapability(*STRING_CAPABILITIES[idx], value=string)
        terminfo.strings[cap.variable] = cap

        idx += 1

    terminfo._reset_index()

    return terminfo

if __name__ == '__main__':
    try:
        terminfo = load_terminfo()

        print('TERMINAL NAME')
        print(terminfo.longname)

        print('\nBOOLEANS')
        for capability in terminfo.booleans.values():
            print('%-27s    %6s    %6s   %s' % (capability.variable, capability.capname, capability.value, repr(capability.value)))
        
        print('\nNUMBERS')
        for capability in terminfo.numbers.values():
            print('%-27s    %6s    %6s  %s' % (capability.variable, capability.capname, capability.value, repr(capability.value)))

        print('\nSTRINGS')
        for capability in terminfo.strings.values():
            print('%-27s    %6s    %s' % (capability.variable, capability.capname, 
                repr(capability.value).replace('\\x1b', '\\E')[1 if sys.version_info[0] >= 3 else 2:-1]
            ))

    except TerminfoError as e:
        print(e, file=sys.stderr)
        sys.exit(-1)
