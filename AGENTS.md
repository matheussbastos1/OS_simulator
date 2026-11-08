# GOVERNANÇA, DIRETRIZES E CONTRATOS PARA AGENTES DE IA — OS SIMULATOR

> **Aviso Fundamental para Agentes:** Este documento é a norma suprema de governança do projeto **OS Simulator**. Qualquer agente de IA ou desenvolvedor humano atuando neste repositório deve obrigatoriamente ler, compreender e aderir a todas as regras, contratos de integração e restrições aqui formalizados antes de propor, modificar ou implementar código.

---

## 1. IDENTIDADE E PROPÓSITO DO PROJETO

- **Nome do Projeto:** OS Simulator
- **Repositório Remoto Oficial:** `https://github.com/matheussbastos1/OS_simulator.git`
- **Versão do Antigravity:** 2.29.1 (aplicativo cliente desktop).
- **Sistema Operacional Hospedeiro (Host):** Windows 11 (plataforma de execução física).
- **Sistema Operacional Representado na Simulação (Target/Guest):** Ubuntu Linux (modelo conceitual de comportamento: hierarquia `/`, permissões rwx/octais, usuários/grupos POSIX, i-nodes, paginação, swap).
- **Linguagem de Programação:** Python 3 (versão mínima 3.11+, compatível com Python 3.13).
- **Paradigma de Desenvolvimento:** Orientação a Objetos (OOP) estrita, arquitetura em camadas, baixo acoplamento e alta coesão.
- **Interface Primária de Interação:** Linha de Comando (CLI) e Shell Interativo simulado.
- **Política de Dependências:** Uso preferencial e quase absoluto da **Biblioteca Padrão do Python** (`dataclasses`, `typing`, `abc`, `enum`, `collections`, `hashlib`, `hmac`, `secrets`, `math`, `struct`, `time`). Dependências externas exigem justificativa técnica formalizada e aprovação explícita.

### 1.1. Objetivo Acadêmico e Entregas Incrementais
O projeto é um simulador educacional de sistemas operacionais construído incrementalmente em quatro etapas acadêmicas unificadas em uma única arquitetura integrada:
1. **Etapa 1 — Sistema de Arquivos:** Hierarquia VFS, i-nodes, blocos de dados, alocações contígua, encadeada (FAT) e indexada, cálculo de fragmentação interna/externa e diagnóstico.
2. **Etapa 2 — Entrada/Saída (I/O) e RAID:** Gerenciamento de requisições (`IORequest`), escalonamento de braço de disco (FCFS, SSTF, SCAN, C-SCAN), simulação de SSD com Wear Leveling e arranjos RAID (0, 1, 4 e 5 com paridade XOR e recuperação de falha).
3. **Etapa 3 — Segurança e Proteção:** Usuários, grupos, autenticação com derivação de chave e salt (PBKDF2-HMAC-SHA256), controle de acesso por listas de controle (ACL) e máscaras rwx/octal, anéis de privilégio (Modo Usuário vs. Modo Kernel), log de auditoria, criptografia de blocos e verificação de integridade/antivírus simulado.
4. **Etapa 4 — Gerenciamento de Memória:** Memória física particionada (área reservada contígua para SO/drivers com compactação `memory_compact` e memória dinâmica paginada), tabelas de páginas, molduras de páginas (frames), MMU e tradução lógica-física, tratamento de falta de página (Page Fault), algoritmos de substituição (LRU e Segunda Chance/Clock) e Swap integrado ao subsistema de disco/RAID.

---

## 2. REGRA FUNDAMENTAL: ISOLAMENTO TOTAL DA SIMULAÇÃO

A regra arquitetural inegociável do projeto é o **Isolamento da Simulação**. O OS Simulator deve simular os recursos de hardware e de sistema operacional exclusivamente através de estruturas de dados gerenciadas na memória do interpretador Python.

### 2.1. Vedações Absolutas (O que NUNCA fazer)
É expressamente proibido a qualquer agente ou desenvolvedor:
1. **Sistema de Arquivos Real:** Criar diretórios reais no Windows 11 (como `os.mkdir`, `pathlib.Path.mkdir`) para representar diretórios do sistema simulado (`/sistema`, `/home`, etc.).
2. **Arquivos Reais:** Criar, ler ou gravar arquivos físicos no Windows para armazenar o conteúdo dos arquivos simulados.
3. **Blocos de Disco Físicos:** Usar arquivos no Windows para representar setores ou blocos físicos de disco.
4. **Alocação de Memória Nativa/mmap:** Chamar APIs Win32, `ctypes` ou mapeamento de arquivos em memória real para representar a RAM simulada.
5. **Permissões do Hospedeiro:** Consultar ou invocar ACLs, permissões NTFS ou atributos de segurança do Windows 11 para resolver permissões de usuários simulados.
6. **Swap no Disco Real:** Utilizar arquivos temporários reais do Windows como área de troca (swap).
7. **E/S Real e Temporizações Forçadas:** Utilizar chamadas de disco do Windows ou comandos de sleep do host para simular a rotação ou o movimento do braço do disco, exceto para fins visuais de animação na CLI se parametrizado.
8. **Subprocessos do Host:** Executar comandos nativos do Ubuntu via WSL, Docker, Cygwin ou comandos PowerShell/CMD para delegar operações que deveriam ser processadas pelos algoritmos internos da simulação.

### 2.2. Implementação Exigida (O que DEVE ser feito)
Todos os recursos simulados existem em estruturas de dados puramente em memória mantidas pelo Python:
- **Diretórios e Arquivos:** Objetos das classes `DirectoryNode`, `FileNode` e `Inode` organizados em grafo/árvore.
- **Blocos de Disco:** Objetos `DiskBlock` contendo `bytearray` ou buffers de tamanho fixo em memória (`4096` bytes).
- **Discos Físicos e RAID:** Objetos `PhysicalDisk` mantendo coleções indexadas de `DiskTrack` e `DiskBlock`; arranjos `RAIDArray` gerenciando a distribuição lógica dos blocos.
- **Memória RAM:** Objetos `PhysicalMemory` gerenciando segmentos contíguos de memória (`MemorySegment`) e listas de molduras (`Frame`).
- **Tabelas de Páginas:** Objetos `PageTable` contendo instâncias de `PageTableEntry`.
- **Swap:** Armazenamento secundário simulado mantido em estruturas gerenciadas pela classe `SwapManager` desacopladas de arquivos reais.
- **Usuários, Grupos e ACLs:** Objetos `User`, `Group`, `ACL` contendo máscaras binárias/octais de permissão.

> **Nota sobre Persistência Externa de Sessão:** Caso uma funcionalidade futura de *snapshot* ou salvamento de sessão seja solicitada, ela será implementada como uma exportação/importação serializada (ex.: JSON/dataclass dump) tratada como ferramenta de backup externa da simulação, sem violar a regra de que os dispositivos e estruturas em tempo de execução operam em isolamento.

---

## 3. PADRÕES DE CÓDIGO E BOAS PRÁTICAS

1. **Princípio da Responsabilidade Única (SRP):** Cada módulo, classe e função deve ter um propósito único e bem delineado.
2. **Separação de Camadas:**
   - **Camada de Apresentação (CLI):** Trata comandos digitados, valida sintaxe preliminar, delega a execução ao Kernel e formata saídas visuais.
   - **Camada de Lógica/Kernel:** Orquestra a execução das operações e media a comunicação entre subsistemas.
   - **Camada de Infraestrutura Simulada:** Implementa os algoritmos de dados, blocos de disco, registradores de memória e tabelas.
3. **Tipagem Estrita (Type Hints):** Uso obrigatório de anotações de tipo completas em assinaturas de funções, atributos de classe e retornos (`typing.Optional`, `typing.Union`, `typing.List`, `typing.Dict`, etc., ou sintaxe nativa Python 3.10+ `X | Y`, `list[X]`).
4. **Documentação de Código:** Docstrings detalhadas (padrão Google ou Sphinx) em todas as classes, métodos públicos e módulos, descrevendo parâmetros, retornos e exceções lançadas.
5. **Tratamento Explícito de Exceções:** Hierarquia de exceções personalizadas herdando de `OSSimulatorException`. Proibido capturar genericamente `except Exception:` sem re-lançamento ou tratamento estruturado.
6. **Convenção de Nomenclatura:**
   - **Código (inglês):** Classes em `PascalCase`, métodos e variáveis em `snake_case`, constantes em `UPPER_SNAKE_CASE`.
   - **Interface e Mensagens da CLI (português):** Mensagens de console, diagnósticos, relatórios e saídas de erro devem ser formatadas em português, preservando os termos técnicos universais de SO (ex.: *i-node*, *page fault*, *frame*, *cluster*, *swap*, *wear leveling*, *parity*, *ACL*).

---

## 4. ESTRUTURA MODULAR DE PACOTES

O projeto deve ser estruturado nos seguintes pacotes:

```text
os_simulator/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── kernel.py             # Orquestrador central e estado compartilhado da simulação
│   ├── exceptions.py         # Hierarquia completa de exceções
│   └── types.py              # Enums globais, type aliases e constantes fundamentais
├── filesystem/
│   ├── __init__.py
│   ├── node.py               # Node, DirectoryNode, FileNode
│   ├── inode.py              # Inode e metadados POSIX
│   ├── vfs.py                # Virtual File System (resolução de caminhos relativos/absolutos)
│   ├── allocation.py         # Estratégias: Contígua, Encadeada (FAT), Indexada
│   └── service.py            # FileSystemService (operações CRUD simuladas)
├── io/
│   ├── __init__.py
│   ├── disk_block.py         # DiskBlock (estruturas de dados e flags)
│   ├── physical_disk.py      # PhysicalDisk e simulação de trilhas/cabeçote
│   ├── io_request.py         # IORequest, enums de operação e prioridade
│   ├── scheduler.py          # Escalonadores de braço: FCFS, SSTF, SCAN, C-SCAN
│   ├── ssd.py                # Simulação de SSD e controlador com Wear Leveling
│   ├── raid.py               # RAIDArray (RAID 0, 1, 4, 5), paridade XOR e rebuild
│   └── service.py            # IOManager / StorageSubsystem
├── security/
│   ├── __init__.py
│   ├── user.py               # User, Group e contextos de credenciais
│   ├── acl.py                # ACL, permissões rwx e conversões octais (0o755, etc.)
│   ├── auth.py               # AuthenticationService (PBKDF2-HMAC-SHA256, salts)
│   ├── audit.py              # AuditLog e eventos de conformidade/acesso
│   ├── crypto.py             # Criptografia de dados em repouso
│   └── integrity.py          # Checagem de integridade SHA-256 e antivírus simulado
├── memory/
│   ├── __init__.py
│   ├── segment.py            # MemorySegment (alocação contígua reservada e fragmentação externa)
│   ├── compaction.py         # Algoritmo de compactação (memory_compact)
│   ├── paging.py             # PageTable, PageTableEntry, Frame e PhysicalMemory
│   ├── mmu.py                # Tradução lógica-física e detecção de Page Fault
│   ├── replacement.py        # Políticas de substituição: LRU e Segunda Chance (Clock)
│   ├── swap.py               # SwapManager integrado ao disco simulado
│   └── service.py            # MemoryManager (orquestração de memória física e virtual)
├── process/
│   ├── __init__.py
│   ├── pcb.py                # Process Control Block (PCB) e estados de processo
│   └── manager.py            # ProcessManager (ciclo de vida: create, execute, terminate)
└── cli/
    ├── __init__.py
    ├── shell.py              # Loop interativo REPL
    ├── parser.py             # Tokenizador e interpretador de comandos
    ├── formatters.py         # Formatadores visuais de saída conforme especificações
    └── commands/             # Handlers individuais dos comandos da CLI
```

---

## 5. CONTRATOS DE INTEGRAÇÃO MULTI-SUBSISTEMA

O OS Simulator é um **sistema coeso e integrado**. As operações solicitadas pelo usuário acionam múltiplos subsistemas através de contratos explícitos mediados pelo `Kernel` ou serviços registrados:

### Contrato 1: `write_file <caminho> "<conteudo>"`
1. **CLI:** Interpreta o comando e extrai usuário atual, caminho e carga de dados.
2. **Security (`SecurityManager`):** Valida a identidade da sessão atual e consulta a ACL do nó pai ou do arquivo existente. Se não possuir permissão `w`, nega a operação, gera evento de falha no `AuditLog` e interrompe o fluxo.
3. **VFS (`VirtualFileSystem`):** Resolve o caminho canônico a partir do diretório de trabalho atual (CWD).
4. **Filesystem (`FileSystemService`):** Localiza ou cria o `Inode`. Determina o número de blocos necessários com base na carga útil e na estratégia de alocação ativa (Contígua, FAT ou Indexada).
5. **Security (Criptografia):** Se o arquivo possuir a flag de criptografia ativa, cifra o payload antes de gravar nos blocos.
6. **I/O (`IOManager`):** Empacota cada gravação de bloco como uma requisição `IORequest` com prioridade associada.
7. **Escalonador (`DiskScheduler`):** Enfileira as requisições e executa o algoritmo de escalonamento ativo (SSTF/SCAN/etc.), calculando o deslocamento do cabeçote.
8. **RAID Controller (`RAIDArray`):** Se o sistema estiver operando sob RAID (ex.: RAID 5), distribui os blocos pelos discos físicos participantes (`stripe`) e calcula o bloco de paridade XOR.
9. **Armazenamento Físico (`PhysicalDisk`):** Atualiza os dados nos objetos `DiskBlock` correspondentes.
10. **Memória / Buffer Cache:** Atualiza ou invalida o buffer cache na memória se os dados estiverem mapeados.

### Contrato 2: `read_file <caminho>`
1. **CLI:** Recebe a solicitação.
2. **Security:** Valida a permissão de leitura (`r`) via ACL e gera log no `AuditLog`.
3. **VFS & Filesystem:** Resolve o caminho e consulta a tabela de blocos do `Inode`.
4. **I/O Manager & Escalonador:** Cria `IORequest` de leitura, despacha no escalonador de disco e move o braço simulado.
5. **RAID Controller:** Lê os blocos dos discos físicos. Se um disco estiver em falha, executa o cálculo de reconstrução on-the-fly via XOR dos demais discos e da paridade.
6. **Security (Criptografia / Integridade):** Descriptografa os dados se aplicável e valida o hash SHA-256 do bloco contra assinaturas armazenadas.
7. **CLI:** Exibe o conteúdo decodificado ou relatório correspondente ao usuário.

### Contrato 3: `create_process <nome> <tamanho_kb> [--reserved]`
1. **Security:** Confirma se o usuário possui permissão de execução ou privilégios de Kernel (necessário caso seja alocado na Área Reservada Contígua).
2. **Process Manager:** Instancia o `Process` (PCB) com estado inicial `READY`.
3. **Memory Manager:**
   - Se for processo crítico de sistema (`--reserved`): Aloca um `MemorySegment` contíguo na Área Reservada via First-Fit / Best-Fit. Se houver fragmentação externa impedindo a alocação, notifica a necessidade de `memory_compact`.
   - Se for processo de usuário convencional: Calcula o total de páginas necessárias ($\lceil \text{tamanho} / \text{page\_size} \rceil$), aloca a `PageTable` do processo e mapeia molduras livres (`Frame`).

### Contrato 4: `terminate_process <pid>`
1. **Process Manager:** Atualiza o estado do processo para `TERMINATED`.
2. **Memory Manager:** Libera todos os segmentos contíguos da Área Reservada ou desocupa todas as molduras de páginas e slots de Swap associados, restaurando a disponibilidade de memória física e limpando referências.
3. **Security:** Registra o encerramento no log de auditoria.

### Contrato 5: `execute_step <pid> <endereco_logico>` / Acesso à Memória
1. **MMU (`MemoryManagementUnit`):** Decompõe o endereço lógico em Número da Página Lógica ($p$) e Deslocamento ($d$).
2. **Page Table Lookup:** Consulta a entrada `PageTableEntry` para a página $p$.
3. **Page Fault Handling:** Se o bit `present == False`:
   - Interrompe a instrução e emite sinal de `PageFaultException`.
   - `MemoryManager` procura uma moldura livre. Se todas as molduras estiverem ocupadas, invoca a política de substituição (LRU ou Segunda Chance).
   - A vítima escolhida, se estiver com bit `dirty == True`, é gravada na área de Swap simulada (acionando o subsistema de I/O).
   - A página requerida é transferida do Swap/armazenamento para a moldura física liberada.
   - A `PageTable` é atualizada com `present = True`, `frame_id` e timestamp/bit de referência atualizado.
4. **Tradução:** Endereço Físico calculado: $( \text{frame\_id} \times \text{frame\_size} ) + d$.

---

## 6. PROTOCOLO DE TRABALHO PARA AGENTES E DESENVOLVEDORES

Ao receber uma ordem de desenvolvimento em qualquer etapa:

1. **Leitura Obrigatória:** Consultar este `AGENTS.md`, o roadmap em `PLAN.md` e a documentação técnica correspondente em `docs/`.
2. **Verificação de Escopo:** Trabalhar exclusivamente na branch da respectiva etapa (`feature/etapa-X-...`). Nunca misturar implementações de fases distintas.
3. **Sem Mudanças Unilaterais:** É proibido alterar os contratos arquiteturais ou assinaturas de métodos base sem atualizar formalmente a documentação e justificar a modificação.
4. **Testes e Ground Truth:** Todo código implementado deve passar obrigatoriamente pelos cenários de teste descritos em `tests/GROUND_TRUTH.md`.
5. **Git e Commits:** Utilizar estritamente o padrão **Conventional Commits** (ex.: `feat(filesystem): implement indexed allocation`). Nunca realizar commits vazios nem usar `--force`.
6. **Preservação de Integridade:** Não inserir credenciais, dados sensíveis ou caminhos absolutos locais do Windows 11 no código.
