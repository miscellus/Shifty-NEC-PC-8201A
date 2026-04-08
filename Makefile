
SHIFTY := build/shifty.co

ASMDIR := tools/asm8085
ASMNAME := asm8085.exe
ASM := $(ASMDIR)/$(ASMNAME)

.PHONY: all clean

all: $(SHIFTY)

$(SHIFTY): $(ASM) build src/shifty.s8085
	$(ASM) -c -o $(SHIFTY) src/shifty.s8085

build:
	mkdir build

$(ASM):
	$(MAKE) -C $(ASMDIR) ASM=$(ASMNAME)

clean:
	$(MAKE) -C $(ASMDIR) clean
	rm -f $(ASM)
	rm -rf build
