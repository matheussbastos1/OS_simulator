# MATRIZ OFICIAL DE GROUND TRUTH E TESTES DETERMINÍSTICOS — OS SIMULATOR

> **Status:** Especificação Oficial (Fase 0)  
> **Objetivo:** Estabelecer a verdade fundamental (*ground truth*) e os critérios exatos de aceitação para os testes de integração e unitários das quatro etapas do simulador.

---

## 1. CENÁRIOS DA ETAPA 1 — SISTEMA DE ARQUIVOS

### Cenário FS-001: Hierarquia de Diretórios e Resolução de Caminhos
- **Identificador:** `FS-001`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Sistema de arquivos recém-formatado com diretório raiz `/` montado.
- **Comandos Executados:**
  ```bash
  mkdir /sistema
  mkdir /sistema/logs
  create /sistema/logs/app.log
  ```
- **Entradas:** Caminhos absolutos fornecidos.
- **Resultado Esperado:**
  - A árvore de nós deve conter `/`, `/sistema` (DirectoryNode), `/sistema/logs` (DirectoryNode) e `/sistema/logs/app.log` (FileNode).
  - O pai de `app.log` deve apontar para `/sistema/logs`.
  - Cada nó deve possuir um i-node distinto atribuído.
- **Critério de Aprovação:** Resolução de caminhos `vfs.resolve("/sistema/logs/../logs/app.log")` retorna a mesma referência de objeto que `vfs.resolve("/sistema/logs/app.log")`.

---

### Cenário FS-002: Alocação Indexada e Fragmentação Interna
- **Identificador:** `FS-002`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Disco simulado com blocos de $4.096$ bytes ($4\text{ KB}$).
- **Comando Executado:**
  ```bash
  write_file /sistema/logs/app.log "<conteudo_de_10240_bytes>"
  ```
- **Entradas:** Carga de dados de exatamente $10.240\text{ bytes}$ ($10\text{ KB}$).
- **Cálculos Esperados:**
  - Tamanho real do arquivo: $10.240\text{ bytes}$.
  - Tamanho do bloco: $4.096\text{ bytes}$.
  - Blocos de dados necessários: $\lceil 10.240 / 4.096 \rceil = \lceil 2,5 \rceil = 3\text{ blocos}$.
  - Espaço total alocado para dados: $3 \times 4.096 = 12.288\text{ bytes}$.
  - Fragmentação Interna: $12.288 - 10.240 = 2.048\text{ bytes}$.
  - Fragmentação Externa: $0\text{ bytes}$ (a alocação indexada aproveita blocos livres não adjacentes).
- **Critério de Aprovação:** Atributos do i-node registram `file_size == 10240`, `len(allocated_blocks) == 3`, e o cálculo do método `get_fragmentation()` retorna `(2048, 0)`.

---

### Cenário FS-003: Validação Comparativa de Estratégias de Alocação
- **Identificador:** `FS-003`
- **Etapa:** 1 (Sistema de Arquivos)
- **Preparação do Estado:** Três sistemas de arquivos idênticos montados com 10 blocos cada, onde os blocos 1 e 5 estão ocupados.
- **Comandos Executados:** Gravar um arquivo de 3 blocos em cada sistema configurado respectivamente com:
  1. Alocação Contígua.
  2. Alocação Encadeada (FAT).
  3. Alocação Indexada.
- **Resultado Esperado:**
  - *Contígua:* Localiza o primeiro ou menor intervalo contíguo livre (blocos 2, 3 e 4).
  - *FAT:* Pode alocar blocos dispersos (ex.: 0, 2, 3), atualizando os ponteiros `0 -> 2 -> 3 -> EOF`.
  - *Indexada:* Aloca 1 bloco para o i-node/índice e 3 blocos para dados em quaisquer posições livres.
- **Critério de Aprovação:** Sucesso na recuperação do conteúdo original nas 3 estratégias.

---

## 2. CENÁRIOS DA ETAPA 2 — ENTRADA E SAÍDA E RAID

### Cenário IO-001: Escalonamento de Disco SSTF
- **Identificador:** `IO-001`
- **Etapa:** 2 (E/S e Escalonamento)
- **Preparação do Estado:** Disco rígido com 200 trilhas (0 a 199). Posição inicial do cabeçote: Trilha 53.
- **Entrada da Fila de Requisições:**
  ```text
  [98, 183, 37, 122, 14]
  ```
- **Cálculo Passo a Passo:**
  1. A partir de 53: distâncias para `[98: 45, 183: 130, 37: 16, 122: 69, 14: 39]`. Menor é 37 ($\Delta = 16$). Cabeçote vai para 37.
  2. A partir de 37: distâncias para `[98: 61, 183: 146, 122: 85, 14: 23]`. Menor é 14 ($\Delta = 23$). Cabeçote vai para 14.
  3. A partir de 14: distâncias para `[98: 84, 183: 169, 122: 108]`. Menor é 98 ($\Delta = 84$). Cabeçote vai para 98.
  4. A partir de 98: distâncias para `[183: 85, 122: 24]`. Menor é 122 ($\Delta = 24$). Cabeçote vai para 122.
  5. A partir de 122: resta 183 ($\Delta = 61$). Cabeçote vai para 183.
- **Cálculo da Movimentação Total:**
  $$16 + 23 + 84 + 24 + 61 = 208\text{ trilhas}$$
- **Critério de Aprovação:** Sequência exata de visitação `[53, 37, 14, 98, 122, 183]` e acumulador `total_head_movement == 208`.

---

### Cenário IO-002: Arranjo RAID 5, Paridade XOR e Reconstrução
- **Identificador:** `IO-002`
- **Etapa:** 2 (RAID e Tolerância a Falhas)
- **Preparação do Estado:** Arranjo RAID 5 com 3 discos físicos ($N = 3$), blocos de $4.096\text{ bytes}$.
- **Comando Executado:** Gravação de um arquivo de $8\text{ KB}$ ($8.192\text{ bytes}$ = 2 blocos de dados).
- **Mapeamento:**
  - Faixa 0: Disco 1 = Bloco de Dados 0 ($D_0$); Disco 2 = Bloco de Dados 1 ($D_1$); Disco 3 = Bloco de Paridade ($P$).
  - Cálculo de Paridade: $P[j] = D_0[j] \oplus D_1[j]$ para $0 \le j < 4096$.
- **Injeção de Falha:**
  - Marcar `physical_disks[1].failed = True` (simulando falha total do Disco 2).
- **Operação de Reconstrução:**
  - Solicitar leitura de $D_1$.
  - Como o Disco 2 está offline, o controlador lê $D_0$ do Disco 1 e $P$ do Disco 3.
  - Reconstrói $D_1$: $D_{1,\text{reconstruído}}[j] = D_0[j] \oplus P[j]$.
- **Critério de Aprovação:** $D_{1,\text{reconstruído}} == D_1$ idêntico byte a byte.

---

## 3. CENÁRIOS DA ETAPA 3 — SEGURANÇA E PROTEÇÃO

### Cenário SEC-001: Autenticação Criptográfica com PBKDF2 e Salt
- **Identificador:** `SEC-001`
- **Etapa:** 3 (Segurança e Controle de Acesso)
- **Preparação do Estado:** Usuário `carlos` cadastrado com salt aleatório e hash derivado de sua senha no grupo `devs`.
- **Comando Executado:**
  ```bash
  login carlos
  # Input de senha válida
  ```
- **Resultado Esperado:**
  - O serviço calcula o hash com o salt registrado e compara via `hmac.compare_digest`.
  - Autenticação bem-sucedida, sessão ativa configurada para `carlos` e evento de sucesso registrado no `AuditLog`.
- **Critério de Aprovação:** `security_manager.active_user.username == "carlos"` e evento presente no log.

---

### Cenário SEC-002: Fiscalização de ACL e Negação de Acesso com Auditoria
- **Identificador:** `SEC-002`
- **Etapa:** 3 (Segurança e Controle de Acesso)
- **Preparação do Estado:**
  - Arquivo: `/sistema/config.sys`
  - Proprietário: `root`
  - Grupo: `admin`
  - Permissões: `750` (`rwxr-x---`)
  - Usuário com sessão ativa: `carlos` (pertencente apenas ao grupo `devs`)
- **Comando Executado:**
  ```bash
  read_file /sistema/config.sys
  ```
- **Avaliação de Permissões:**
  1. `carlos != root` (não é proprietário $\implies$ não aplica `rwx`).
  2. `devs != admin` (não pertence ao grupo do arquivo $\implies$ não aplica `r-x`).
  3. Aplica permissões de "outros": `---` ($000$ binário $\implies$ sem leitura, sem escrita, sem execução).
- **Resultado Esperado:** Acesso bloqueado, exceção `PermissionDeniedException` lançada e evento registrado no `AuditLog` com tipo `ACCESS_DENIED`, usuário `carlos` e recurso `/sistema/config.sys`.
- **Critério de Aprovação:** Conteúdo não é lido e evento de negação consta no log de auditoria.

---

### Cenário SEC-003: Verificação de Integridade e Detecção de Adulteração
- **Identificador:** `SEC-003`
- **Etapa:** 3 (Segurança e Proteção)
- **Preparação do Estado:** Arquivo gravado com checksum SHA-256 armazenado em seus metadados.
- **Injeção de Anomalia:** Alterar arbitrariamente 1 byte na memória interna do bloco físico de dados correspondente.
- **Comando Executado:**
  ```bash
  antivirus_scan /sistema
  ```
- **Resultado Esperado:**
  - O verificador recalcula o SHA-256 do bloco e detecta discrepância com o hash armazenado.
  - Alerta de violação de integridade emitido na CLI e logado na auditoria.
- **Critério de Aprovação:** Detecção precisa do bloco e arquivo adulterado.

---

## 4. CENÁRIOS DA ETAPA 4 — GERENCIAMENTO DE MEMÓRIA

### Cenário MEM-001: Alocação Contígua na Área Reservada e Fragmentação Externa
- **Identificador:** `MEM-001`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:**
  - Área Reservada Total: $4.096\text{ KB}$ ($4\text{ MB}$).
  - Núcleo Base (SO): $1.024\text{ KB}$ (faixa $0 - 1023\text{ KB}$).
- **Comandos Executados:**
  ```bash
  create_process Kernel_DiskDriver 512 --reserved
  create_process Kernel_NetDriver 1024 --reserved
  create_process Kernel_CryptoEngine 512 --reserved
  ```
  - Estado da memória:
    - $[0000 - 1023\text{ KB}]$: Núcleo Base ($1024\text{ KB}$)
    - $[1024 - 1535\text{ KB}]$: Kernel_DiskDriver ($512\text{ KB}$)
    - $[1536 - 2559\text{ KB}]$: Kernel_NetDriver ($1024\text{ KB}$)
    - $[2560 - 3071\text{ KB}]$: Kernel_CryptoEngine ($512\text{ KB}$)
    - $[3072 - 4095\text{ KB}]$: Espaço Livre Final ($1024\text{ KB}$)
- **Encerramento de Processo:**
  ```bash
  terminate_process <PID_Kernel_NetDriver>
  ```
  - Libera a faixa $[1536 - 2559\text{ KB}]$, criando um buraco livre de $1.024\text{ KB}$.
- **Cálculo da Fragmentação Externa:**
  - Espaço livre total: $1.024\text{ KB} + 1.024\text{ KB} = 2.048\text{ KB}$.
  - Maior bloco contíguo livre: $1.024\text{ KB}$.
  - Se um processo requerer $1.536\text{ KB}$ contíguos: a alocação falha por fragmentação externa, apesar de haver $2.048\text{ KB}$ livres!
- **Critério de Aprovação:** Diagnóstico `memory_status` reporta exatamente $2.048\text{ KB}$ livres totais e maior bloco livre de $1.024\text{ KB}$.

---

### Cenário MEM-002: Desfragmentação Deslizante (`memory_compact`)
- **Identificador:** `MEM-002`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:** Estado resultante imediatamente após o cenário `MEM-001`.
- **Comando Executado:**
  ```bash
  memory_compact
  ```
- **Operação de Reorganização:**
  - O segmento `Kernel_CryptoEngine` ($512\text{ KB}$) é deslocado para a faixa contígua $[1536 - 2047\text{ KB}]$.
  - Os dois blocos livres ($1.024\text{ KB} + 1.024\text{ KB}$) são consolidados no final: faixa $[2048 - 4095\text{ KB}]$ ($2.048\text{ KB}$ contíguos).
- **Cálculo Posterior:**
  - Maior bloco livre contíguo: $2.048\text{ KB}$.
  - Fragmentação Externa: $0\text{ KB}$.
  - Tentativa de alocar $1.536\text{ KB}$ contíguos agora obtém sucesso absoluto.
- **Critério de Aprovação:** Segmento contíguo de $2.048\text{ KB}$ livre disponível.

---

### Cenário MEM-003: Memória Virtual, Paginação e Fragmentação Interna
- **Identificador:** `MEM-003`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:** Área Dinâmica configurada com páginas de $4.096\text{ bytes}$ ($4\text{ KB}$).
- **Comando Executado:**
  ```bash
  create_process App_Navegador 10
  ```
- **Cálculos Esperados:**
  - Tamanho do processo: $10\text{ KB} = 10.240\text{ bytes}$.
  - Tamanho da página/frame: $4.096\text{ bytes}$.
  - Páginas lógicas necessárias: $\lceil 10.240 / 4.096 \rceil = 3\text{ páginas}$ (Páginas 0, 1 e 2).
  - Distribuição:
    - Página 0: $4.096\text{ bytes}$ ocupados.
    - Página 1: $4.096\text{ bytes}$ ocupados.
    - Página 2: $2.048\text{ bytes}$ ocupados.
  - Fragmentação Interna da Página 2: $4.096 - 2.048 = 2.048\text{ bytes}$.
- **Critério de Aprovação:** A `PageTable` possui 3 entradas e a fragmentação interna total calculada é $2.048\text{ bytes}$.

---

### Cenário MEM-004: Tradução de Endereço Virtual via MMU
- **Identificador:** `MEM-004`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:** Processo `App_Navegador` com Página 1 mapeada na moldura física $5$ (`frame_id = 5`). Tamanho de página = $4.096\text{ bytes}$.
- **Comando Executado:**
  ```bash
  translate_address <PID> 4100
  ```
- **Cálculo da MMU:**
  - Número da Página: $p = \lfloor 4100 / 4096 \rfloor = 1$.
  - Deslocamento (Offset): $d = 4100 \pmod{4096} = 4$.
  - Moldura Física: $f = 5$.
  - Endereço Físico: $(f \times \text{page\_size}) + d = (5 \times 4096) + 4 = 20.480 + 4 = 20.484$.
- **Critério de Aprovação:** `translate_address` retorna exatamente o endereço físico $20.484$.

---

### Cenário MEM-005: Falta de Página (Page Fault), Substituição LRU e Swap
- **Identificador:** `MEM-005`
- **Etapa:** 4 (Gerenciamento de Memória)
- **Preparação do Estado:**
  - Memória física paginada configurada com apenas 2 molduras físicas totais para teste de saturação.
  - Moldura 0 hospeda Página 0 (acessada no tempo $t=10$).
  - Moldura 1 hospeda Página 1 (acessada no tempo $t=20$, marcada como `dirty = True`).
- **Ação Executada:** Acesso à Página 2 (`present == False`).
- **Sequência Esperada:**
  1. MMU detecta `present == False` e lança `PageFaultException`.
  2. Memória saturada $\to$ invoca substituição LRU.
  3. Compara timestamps: Página 0 ($t=10$) é mais antiga que Página 1 ($t=20$). Vítima eleita: Página 0.
  4. Página 0 é removida da moldura 0 (`present = False`, `frame_id = None`).
  5. Página 2 é transferida do Swap/armazenamento para a moldura 0.
  6. Entrada da Página 2 atualizada: `present = True`, `frame_id = 0`.
- **Critério de Aprovação:** Moldura 0 passa a conter a Página 2; Página 0 passa para `present = False`.

---

## 5. NOTAS TÉCNICAS SOBRE CONSISTÊNCIA CONCEITUAL E MATEMÁTICA

Para evitar divergências na interpretação acadêmica:
1. **Unidades de Medida:** $1\text{ KB} = 1.024\text{ bytes}$ (padrão binário KiB utilizado em arquitetura de SO). Tamanhos devem ser computados sempre em bytes internamente, exibindo conversão formatada na CLI.
2. **Capacidade Útil de RAID 5:** Em um arranjo de $N$ discos de capacidade $C$, a capacidade útil de dados é $(N - 1) \times C$, pois o equivalente a 1 disco é consumido pelas paridades distribuídas.
3. **Endereçamento da Área Reservada vs. Paginada:** A Área Reservada opera sobre endereços físicos contíguos de memória real; a Área Paginada opera sob o isolamento da MMU e tabelas de páginas por processo.
