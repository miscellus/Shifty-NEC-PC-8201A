
SHIFTY := build/shifty.co

ASMDIR := tools/asm8085
ASMNAME := asm8085.exe
ASM := $(ASMDIR)/$(ASMNAME)

.PHONY: all clean

all: $(SHIFTY)

$(SHIFTY): $(ASM) build src/shifty.s8085 src/tiles.s8085 src/levels.s8085 Makefile
	$(ASM) -c -o $(SHIFTY) src/shifty.s8085
	$(ASM) -o $(SHIFTY).bin src/shifty.s8085
	python tools/bin2bas.py $(SHIFTY).bin -o $(SHIFTY).bas

src/tiles.s8085: $(wildcard assets/tile_images/*.png)
	python tools/png2asm.py assets/tile_images src/tiles.s8085

src/levels.s8085: assets/levels.txt src/tiles.s8085
	python tools/levels2asm.py assets/levels.txt src/tiles.s8085 src/levels.s8085

build:
	mkdir build

$(ASM):
	$(MAKE) -C $(ASMDIR) ASM=$(ASMNAME)

clean:
	$(MAKE) -C $(ASMDIR) clean
	rm -f $(ASM)
	rm -rf build
