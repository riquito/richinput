from __future__ import print_function

import os, sys, tty, termios, codecs, unicodedata
import threading
from contextlib import contextmanager

import select, terminfo, struct, signal, fcntl

class UnicodeMixin(object):
  """Mixin class to handle defining the proper __str__/__unicode__
  methods in Python 2 or 3."""

  if sys.version_info[0] >= 3: # Python 3
      def __str__(self):
          return self.__unicode__()
  else:  # Python 2
      def __str__(self):
          return self.__unicode__().encode(sys.stdout.encoding or 'utf-8')

def encode_string_decorator(func):
    if sys.version_info[0] < 3:
        def inner(*args, **kwargs):
            return func(*args, **kwargs).encode(sys.stdout.encoding or 'utf-8')
        return inner
    else:
        return func

class Key(UnicodeMixin):
    def __init__(self, value):
        self.value = value
    
    @encode_string_decorator
    def __repr__(self):
        return u'<%s %r>' % (self.__class__.__name__, self.value)

class ControlKey(Key):
    def __unicode__(self):
        return u''

class PrintableChar(Key):
    def __unicode__(self):
        return self.value

class EscapeSequence(UnicodeMixin):
    def __init__(self, capability):
        self.capability = capability
        self.value = self.capability.value
    
    def __unicode__(self):
        return u''

    @encode_string_decorator
    def __repr__(self):
        return repr(self.capability)

class StartEscapeSequenceException(Exception):
    def __init__(self, value):
        self.value = ControlKey(value)

@contextmanager
def nonblocking_input():
    fd = sys.stdin.fileno()
    old_tcattrs = termios.tcgetattr(fd)
    old_fl = fcntl.fcntl(fd, fcntl.F_GETFL)

    try:
        fcntl.fcntl(fd, fcntl.F_SETFL, old_fl | os.O_NONBLOCK)
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_tcattrs)
        fcntl.fcntl(fd, fcntl.F_SETFL, old_fl)

def get_char(prompt=''):
    with nonblocking_input():
        if prompt:
            # This is needed for cases like escape sequences that write
            # on stdin (e.g \x1b[6n write on stdin the cursor position)
            # (otherwise once in a while you may loose the 'answer')
            sys.stdout.write(prompt)
            sys.stdout.flush()
        
        # encoding aware reader 
        # XXX codecs.getreader raised IOError(11) on some machines
        # (even if select said that there was data to read)
        read = sys.stdin.read
        if sys.version_info[0] < 3:
            read = lambda *x: sys.stdin.read(*x).decode(sys.stdin.encoding)

        fd = sys.stdin.fileno()
        while True:
            # wait for data on the file descriptor
            try:
                select.select([fd],[],[])
                for c in read():
                    yield c
            except select.error as e:
                if e.args[0] == 4: # Interrupted system call
                    pass
                else:
                    raise e

def get_rich_char(prompt=u'', term=None):
    """Iterator that returns the next meaningful input given to a terminal,
    whenever a key is pressed.
    `term` is an instance of terminfo.Term, needed to understand what the
    escape sequences mean.
    
    The yielded value will be one of
    - PrintableChar
    - ControlKey
    - EscapeSequence
    
    Note that only PrintableChar has a non-empty string representation,
    so something like the following may come in handy
    >>> print(''.join(get_rich_char(term)))
    """

    if not term:
        term = terminfo.load_terminfo()

    iterator = get_char(prompt)
    for c in iterator:
        try:
            raise_if_start_escape_sequence(c)
            
            if is_char_printable(c):
                yield PrintableChar(c)
            else:
                yield ControlKey(c)
        
        except StartEscapeSequenceException as e:
            # We use a cicle because the input may be in the form
            # ESC-ESC-* rest of the sequence
            while True:
                try:
                    sequence = consume_escape_sequence(iterator, c)
                    yield EscapeSequence(term.detect(sequence))
                    break
                except StartEscapeSequenceException as e:
                    c = e.value

    raise StopIteration
        

def is_char_printable(c):
    """Check whether `c` is a printable char according to unicode."""
    return not unicodedata.category(c).startswith('C')

def is_char_interrupt(c):
    """Check whether `c` is EOT (end of transmission, ^D)."""
    return c == u'\x04'

def is_char_backspace(c):
    """Check whether `c` is backspace."""
    # check for both BACKSPACE and DELETE (which is not the delete key)
    return c in (u'\x08', u'\x7F')

def is_char_esc(c):
    """Check whether `c` is the escape character."""
    return c == u'\x1b'

def is_char_single_character_csi(c):
    """Check whether `c` is the single character CSI."""
    return c == u'\x9b'

def raise_if_start_escape_sequence(c):
    """If `c` is ESC or the single character CSI,
    raise `StartEscapeSequenceException`."""
    if (is_char_single_character_csi(c) or is_char_esc(c)):
        raise StartEscapeSequenceException(c)

def consume_escape_sequence(iterator, starter):
    """Given an input `iterator` and the character that started an escape
    sequence, consume the whole escape sequence and return it.
    
    May raise StartEscapeSequenceException if a new escape sequence
    is started midway.
    
    The escape sequence is returned as an unicode string and is always
    formatted as if the extended format (ESC + [) had been used."""

    seq = [u'['] if is_char_single_character_csi(starter) else [next(iterator)]
    raise_if_start_escape_sequence(seq[-1])

    if seq[-1] == u'[':
        seq.append(next(iterator))
        raise_if_start_escape_sequence(seq[-1])
        while not (64 <= ord(seq[-1]) <= 126 or seq[-1] == 36):
            seq.append(next(iterator))
            raise_if_start_escape_sequence(seq[-1])
    elif seq[-1] == u'O': # read 1 more byte
        seq.append(next(iterator))
        raise_if_start_escape_sequence(seq[-1])
    else:
        pass

    return u'\x1b' + u''.join(seq)

def is_capability_delete(capability):
    return capability.capname == 'kdch1'

def is_capability_home(capability):
    return capability.capname == 'khome'

def is_capability_end(capability):
    return capability.capname == 'kend'

def is_capability_arrow_left(capability): 
    return capability.capname == 'kcub1'

def is_capability_arrow_right(capability):
    return capability.capname == 'kcuf1'

def is_capability_arrow_up(capability):
    return capability.capname == 'kcup1'

def is_capability_arrow_down(capability):
    return capability.capname == 'kcud1'

def get_cursor_position():
    """Write an escape sequence to ask for the current cursor position.
    Since the result is written on the standard input, this function
    should not be used if you expect that your input has been pasted,
    because the characters in the buffer would be read before the
    answer about the cursor."""
    
    # "cursor position report" in ECMA-48.
    it = get_char(u'\x1b[6n')
    sequence = consume_escape_sequence(it, next(it))

    # sequence format is \x1b[<row>;<col>R
    return tuple(int(x) for x in sequence[2:-1].split(u';'))

class IndexedLine(object):
    # index on `text` (not the column on terminal)
    def __init__(self, text=u'', idx=0):
        self.idx = idx
        self.text = text

    def insert(self, text):
        self.text = self.text[:self.idx] + text + self.text[self.idx:]
        self.move_cursor_forward(len(text))

    def delete_backward(self):
        if self.idx > 0:
            self.text = self.text[:self.idx-1] + self.text[self.idx:]
            self.move_cursor_backward()
    
    def delete_forward(self):
        if self.idx < len(self.text):
            self.text = self.text[:self.idx] + self.text[self.idx+1:]
    
    def move_cursor_backward(self, steps=1):
        idx = self.idx
        self.idx = max(0, self.idx - steps)
        return idx != self.idx

    def move_cursor_forward(self, steps=1):
        idx = self.idx
        self.idx = min(len(self.text), self.idx + steps)
        return idx != self.idx
     
    def move_cursor_home(self):
        idx = self.idx
        self.idx = 0
        return idx != self.idx

    def move_cursor_end(self):
        idx = self.idx
        self.idx = len(self.text)
        return idx != self.idx

class VTerm(object):
    def __init__(self, term, x=0, y=0):
        self.term = term
        self.cursor = [x, y]
        self.size = (0, 0) # width, height
        self._update_size()
        signal.signal(signal.SIGWINCH, self._update_size)

    def _update_size(self, *args):
        rows, cols, height, width = struct.unpack('HHHH',
            fcntl.ioctl(sys.stdin.fileno(),
                  termios.TIOCGWINSZ, 
                  struct.pack('HHHH', 0, 0, 0, 0)))
        self.size = (cols, rows)

        if args: # window has been resized
            row, col = get_cursor_position()
            self.cursor = [col, row]
    
    def get_size(self):
        return self.size

    def move_cursor_forward(self, steps=1, update_idx_only=False):
        if not steps:
            return

        width, height = self.size
        x, y = self.cursor

        down_steps = 0

        if x + steps <= width:
            # stay on the same line
            self.cursor[0] += steps
        else:
            # we are going down
            self.cursor[0] = (x + steps) % width or width
            down_steps = int((x + steps -1) / float(width))
            self.cursor[1] = y + down_steps

        if down_steps and not update_idx_only:
            sys.stdout.write(u'\r' + u'\n' * down_steps)
            x = 1

        # now we are on the right line
        if update_idx_only or x == self.cursor[0]:
            pass
        elif x < self.cursor[0]:
            sys.stdout.write(self.term.get('cuf1').value * (self.cursor[0] - x))
        else:
            sys.stdout.write(self.term.get('cub1').value * (x - self.cursor[0]))
        
    
    def move_cursor_backward(self, steps=1, update_idx_only=False):
        if not steps:
            return
        
        width = self.size[0]
        x, y = self.cursor

        if steps < x:
            # stay on the same line
            self.cursor[0] -= steps
        else:
            # we are going up
            self.cursor[0] = (x - steps) % width or width
            self.cursor[1] = y - 1 + int((x - steps) / float(width))

        if not update_idx_only:
            sys.stdout.write(self.term.get('cub1').value * steps)

    def write(self, text):
        sys.stdout.write(text)
        self.move_cursor_forward(steps=len(text), update_idx_only=True)
        sys.stdout.flush()

class RichLine(object):
    def __init__(self, term=None, vterm=None, iline=None):
        if not term:
            term = terminfo.load_terminfo()
        
        if not vterm:
            row, col = get_cursor_position()
            vterm = VTerm(term, x=col, y=row)
        
        if not iline:
            iline = IndexedLine()
        
        self.term = term
        self.vterm = vterm
        self.iline = iline
    
    def read(self, cb=None, eot=u'\n', prompt=u''):
        for el, prev_text, text, prev_idx, idx in self.__iter__(cb, prompt):
            if el.value in eot:
                break
        
        return self.iline.text

    def __iter__(self, cb=None, prompt=u''):
        if cb:
            that_cb = cb
            cb = lambda f,*args: that_cb(update_vterm, *args)
        else:
            cb = update_vterm

        prev_text = self.iline.text
        prev_idx = self.iline.idx

        if prompt:
            # we must update the starting cursor postion
            self.vterm.move_cursor_forward(len(prompt), update_idx_only=True)

        
        for key_event in get_rich_char(prompt, self.term):
            if isinstance(key_event, PrintableChar):
                self.iline.insert(key_event.value)
            elif is_char_backspace(key_event.value):
                self.iline.delete_backward()
            elif isinstance(key_event, EscapeSequence) and is_capability_delete(key_event.capability):
                self.iline.delete_forward()
            elif is_char_interrupt(key_event.value):
                raise StopIteration

            yield (key_event, prev_text, self.iline.text, prev_idx, self.iline.idx)
            
            cb(None, key_event, self.term, self.vterm, self.iline, prev_text, self.iline.text, prev_idx, self.iline.idx)
            
            prev_text = self.iline.text
            prev_idx = self.iline.idx

def update_vterm(cb, key_event, term, vterm, iline, previous, current, prev_idx, next_idx):
    cb = cb or (lambda f, *args: args)

    if previous != current:
        
        # detect a common prefix to rewrite as less as possible
        prefix = os.path.commonprefix([previous, current])

        # move the cursor to the end of the longest common prefix
        if len(prefix) < prev_idx:
            vterm.move_cursor_backward(prev_idx - len(prefix))
        elif len(prefix) > prev_idx:
            vterm.move_cursor_forward(len(prefix) - prev_idx)
        
        # clear text until the end of the screen
        sys.stdout.write(term.get(u'clr_eos').value)
        
        # write the new content
        vterm.write(current[len(prefix):])
        
        # set the cursor at the end of the newly inserted text
        vterm.move_cursor_backward(len(current) - next_idx)
    
    elif isinstance(key_event, EscapeSequence):
        if is_capability_arrow_left(key_event.capability):
            moved = iline.move_cursor_backward()
            if moved:
                vterm.move_cursor_backward()
        elif is_capability_arrow_right(key_event.capability):
            moved = iline.move_cursor_forward()
            if moved:
                vterm.move_cursor_forward()
        elif is_capability_home(key_event.capability):
            moved = iline.move_cursor_home()
            if moved:
                vterm.move_cursor_backward(prev_idx)
        elif is_capability_end(key_event.capability):
            moved = iline.move_cursor_end()
            if moved:
                vterm.move_cursor_forward(len(current)-prev_idx)

    sys.stdout.flush()
    return cb(key_event, term, vterm, iline, previous, current, prev_idx, next_idx)


class RichPassword(RichLine):
    def __init__(self, *args):
        super(RichPassword, self).__init__(*args)
        self.clear_text = False
        self.timer = None
        self.replace_event = threading.Event()
        self.replace_event.set()
    
    def read(self, cb=None, eot=u'\n', prompt=u''):
        if not cb:
            cb = lambda f, *args: f(None, *args)

        inner_cb = lambda f, *args: cb(lambda z,*k: self._on_key_pressed(f, *k), *args)
        
        pw = super(RichPassword, self).read(inner_cb, eot, prompt)
        
        self.replace_previous_char(self.iline.idx)
        
        return pw
    
    def _on_key_pressed(self, cb, key_event, term, vterm, iline, previous, current, prev_idx, next_idx):
        self.replace_event.wait()
        if self.timer:
            self.timer.cancel()
        
        # when F1 is pressed, toggle the asterisks
        if isinstance(key_event, EscapeSequence) and key_event.capability.capname == 'kf1':
            self.clear_text = not self.clear_text
            if not self.clear_text:
                current = '*' * len(current)

            vterm.move_cursor_backward(prev_idx)
            vterm.write(current)
            vterm.move_cursor_backward(len(current) - next_idx)
            sys.stdout.flush()
            
            return cb(None, key_event, term, vterm, iline, previous, current, prev_idx, next_idx)

        if not self.clear_text and not is_char_backspace(key_event.value): 
            self.replace_previous_char(prev_idx)
        
        if not self.clear_text and current and previous != current:

            # Transform `current` while keeping the string at the same length (otherwise I should modify 
            # indexes and cursor in iline and vterm.)
            if len(current) > len(previous):
                latest_char = current[prev_idx:prev_idx + 1]
                current = u'*' * len(current)
                current = current[:prev_idx] + latest_char + current[prev_idx+1:]
                # after one second we'll make the last typed character become an asterisk
                self.timer = threading.Timer(1, self.on_timer_elapsed, [self.replace_event])
                self.timer.start()
            else:
                current = u'*' * len(current)

        return cb(None, key_event, term, vterm, iline, previous, current, prev_idx, next_idx)

    def replace_previous_char(self, idx, new_char=u'*'):
        if not idx:
            return
        self.vterm.move_cursor_backward(1)
        self.vterm.write(u'*')
    
    def on_timer_elapsed(self, event):
        event.clear()
        self.replace_previous_char(self.iline.idx)
        event.set()


if __name__ == '__main__':
    color_idx = 1
    def colorful_string(cb, *args):
        global color_idx
        sys.stdout.write('\033[1;%dm' % ((color_idx % 8) + 30))
        color_idx += 1

        res = cb(None, *args)
        sys.stdout.write('\033[0m')
        return res

    def up(cb, key_event, term, vterm, iline, previous, current, prev_idx, next_idx):
        if isinstance(key_event, PrintableChar):
            key_event.value = key_event.value.upper()
            current = current[:-1] + key_event.value
            iline.text = current

        return colorful_string(cb, key_event, term, vterm, iline, previous, current, prev_idx, next_idx)

    richline = RichLine()
    text = richline.read(cb=up, prompt='Write what you want, try home key, arrows, canc, word-wrap,...: ')
    print('\nYou wrote: ' + text)
    
    richpw = RichPassword()
    pw = richpw.read(cb=colorful_string)
    print('\nPw is: ' + pw)
    

