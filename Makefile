# Shortcuts for people who have make. Everything here just calls ap30.py,
# which works the same on macOS, Linux and Windows:  python ap30.py help
PY     ?= python3
VOLUME ?= /Volumes/NO NAME
ROMS   ?= roms/gameboy
IMAGE  ?= build/gb/HIFIYF18.IMG

help:        ; @$(PY) ap30.py help
setup check: ; $(PY) ap30.py check
info:        ; $(PY) ap30.py info
unpack:      ; $(PY) ap30.py unpack
gb:          ; $(PY) ap30.py gb $(if $(DATE),--date $(DATE),)
gw:          ; $(PY) ap30.py gw --rom "$(ROM)" $(if $(SVG),--svg "$(SVG)",) $(if $(KEYS),--keys "$(KEYS)",)
gw-demo:     ; $(PY) ap30.py gw-demo
rollback:    ; $(PY) ap30.py rollback $(if $(DATE),--date $(DATE),)
flash:       ; $(PY) ap30.py flash "$(VOLUME)" --image $(IMAGE)
flash-roms:  ; $(PY) ap30.py flash "$(VOLUME)" --image $(IMAGE) --roms "$(ROMS)"
roms-only:   ; $(PY) ap30.py flash "$(VOLUME)" --no-image --roms "$(ROMS)"
test:        ; $(PY) ap30.py test
test-gb:     ; $(PY) ap30.py test-gb "$(ROM)"
clean:       ; rm -rf build

.PHONY: help setup check info unpack gb gw gw-demo rollback flash flash-roms roms-only test test-gb clean
