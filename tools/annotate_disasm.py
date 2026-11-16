import re,sys
code=open(sys.argv[1],'rb').read()
def cstr(a):
    if not (0<=a<len(code)): return None
    e=code.find(b'\0',a)
    s=code[a:e]
    if 3<=len(s)<200 and all(32<=c<127 or c in (10,13) for c in s): return s.decode().replace('\n','\\n')
    return None
sym=re.compile(r'<_binary_c_bin_(?:start|end)\+0x([0-9a-f]+)>')
out=open(sys.argv[3],'w')
for l in open(sys.argv[2]):
    l=l.rstrip('\n')
    m=re.match(r'\s*([0-9a-f]+):\s+(.*)',l)
    if not m: continue
    a=int(m.group(1),16); ins=m.group(2)
    note=''
    t=sym.search(ins)
    ins2=sym.sub('',ins)
    ins2=re.sub(r'\s*@ imm = #-?0x[0-9a-f]+','',ins2)
    ma=re.match(r'adr(?:\.w)?\s+\w+, #(-?\d+)',ins)
    if ma:
        tgt=((a+4)&~3)+int(ma.group(1))
        s=cstr(tgt) or cstr(tgt+1) or cstr(tgt-1)
        note=' ; -> 0x%x %s'%(tgt, repr(s) if s else '')
    elif ins.startswith('ldr') and '[pc' in ins:
        mm=re.search(r'@ 0x([0-9a-f]+)',ins)
        if mm:
            p=int(mm.group(1),16)
            if p+4<=len(code):
                v=int.from_bytes(code[p:p+4],'little'); note=' ; =0x%08x'%v
                s=cstr(v)
                if s: note+=' '+repr(s)
        ins2=re.sub(r'\s*@ 0x[0-9a-f]+','',ins2)
    elif t and ins.startswith(('bl','b')):
        ins2=ins2.rstrip()+' 0x%x'%int(t.group(1),16) if '0x' not in ins2 else ins2
    out.write('%6x: %s%s\n'%(a,ins2.strip(),note))
