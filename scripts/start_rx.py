# Ghidra preScript: mark RX entry point and start disassembly from reset vector target
from ghidra.app.cmd.disassemble import DisassembleCommand

reset_vec = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress('fffffffc')
target = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress('ffe80000')
currentProgram.getSymbolTable().addExternalEntryPoint(target)
DisassembleCommand(target, None, True).applyTo(currentProgram, monitor)
