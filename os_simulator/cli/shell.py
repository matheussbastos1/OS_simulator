"""Interactive shell REPL for OS Simulator."""

import sys
from typing import Optional

from os_simulator.cli.commands import CommandDispatcher
from os_simulator.core.simulation_kernel import SimulationKernel


class InteractiveShell:
    """Provides interactive terminal interface and command evaluation loop."""

    def __init__(self, kernel: Optional[SimulationKernel] = None):
        self.kernel = kernel or SimulationKernel()
        self.dispatcher = CommandDispatcher(self.kernel)

    def print_banner(self) -> None:
        """Display startup message."""
        print("Iniciando OS Simulator (Ubuntu Linux sobre Windows 11)...")
        print("Kernel inicializado com sucesso. Digite 'help' para comandos.")
        print()

    def run(self) -> None:
        """Execute interactive REPL loop."""
        self.print_banner()

        while self.kernel.is_running:
            try:
                prompt = self.kernel.get_prompt()
                line = input(prompt)
                trimmed = line.strip()

                if not trimmed:
                    continue

                if trimmed.lower() in ("exit", "quit"):
                    print("Encerrando OS Simulator. Até logo!")
                    break

                result = self.dispatcher.execute_line(trimmed)
                if result.output:
                    print(result.output)
                if not result.success and result.error:
                    print(f"Erro: {result.error}")

            except (KeyboardInterrupt, EOFError):
                print("\nEncerrando OS Simulator...")
                break


def main() -> None:
    """CLI entrypoint."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    shell = InteractiveShell()
    shell.run()


if __name__ == "__main__":
    main()
