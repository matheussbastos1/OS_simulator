# DICIONÁRIO OFICIAL DA CLI E PADRÕES DE SAÍDA — OS SIMULATOR

> **Status:** Especificação Oficial (Fase 0)  
> **Objetivo:** Estabelecer o contrato formal da interface de linha de comando (CLI), sintaxe de comandos, permissões, parâmetros e fidelidade visual aos exemplos de saída do simulador.

---

## 1. DIRETRIZES GERAIS DA CLI

1. **Prompt Interativo Padrão:**  
   `[usuario@ubuntu-simulator:caminho_atual]$ ` (para usuários comuns).  
   `[root@ubuntu-simulator:caminho_atual]# ` (para o superusuário root).
2. **Linguagem das Mensagens:** Saídas visuais, títulos, relatórios de diagnóstico e descrições de erro devem ser impressos em língua portuguesa, preservando terminologias técnicas consolidadas (ex.: *i-node*, *frame*, *page fault*, *cluster*, *swap*, *wear leveling*, *ACL*).
3. **Tratamento de Argumentos:** Argumentos contendo espaços devem ser passados entre aspas duplas (`"conteudo do arquivo"`).

---

## 2. CATÁLOGO COMPLETO DE COMANDOS DA CLI

### 2.1. `mkdir`
- **Sintaxe:** `mkdir <caminho_diretorio>`
- **Parâmetros Obrigatórios:** `<caminho_diretorio>` (caminho relativo ou absoluto).
- **Parâmetros Opcionais:** `-p` (criar diretórios intermediários se inexistentes).
- **Pré-condições:** O diretório pai deve existir; não pode existir nó com mesmo nome.
- **Permissões Necessárias:** Permissão de escrita (`w`) e execução (`x`) no diretório pai.
- **Subsistema Responsável:** `filesystem` (VFS).
- **Resultado Esperado:** Diretório criado na hierarquia com i-node associado e permissões padrão (0o755).
- **Mensagens de Erro:**
  - `Erro: Permissão negada para criar diretório em '<pai>'.`
  - `Erro: Diretório '<caminho>' já existe.`
  - `Erro: Caminho pai inexistente.`

---

### 2.2. `create`
- **Sintaxe:** `create <caminho_arquivo> [--strategy=<contiguous|fat|indexed>]`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`.
- **Parâmetros Opcionais:** `--strategy` (define a estratégia de alocação; padrão: `indexed`).
- **Pré-condições:** O diretório pai deve existir.
- **Permissões Necessárias:** Permissão `w` e `x` no diretório pai.
- **Subsistema Responsável:** `filesystem`.
- **Resultado Esperado:** Criação de arquivo vazio (tamanho 0 bytes) com novo `Inode` registrado.
- **Mensagens de Erro:**
  - `Erro: Permissão negada no diretório pai.`
  - `Erro: Arquivo já existe.`
  - `Erro: Tabela de i-nodes esgotada.`

---

### 2.3. `write_file`
- **Sintaxe:** `write_file <caminho_arquivo> "<conteudo>"`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`, `"<conteudo>"`.
- **Parâmetros Opcionais:** `--append` (anexar ao invés de sobrescrever).
- **Pré-condições:** O arquivo deve existir (ou ser criado implicitamente) e o usuário deve ter permissão.
- **Permissões Necessárias:** Permissão `w` no arquivo.
- **Subsistema Responsável:** Integração `security` $\to$ `filesystem` $\to$ `io` $\to$ `raid`.
- **Resultado Esperado:** Gravação física simulada nos blocos, atualização de metadados do i-node, acionamento do escalonador de E/S e exibição de relatório de gravação com blocos alocados e fragmentação calculada.
- **Mensagens de Erro:**
  - `Erro: Permissão negada para escrita no arquivo '<caminho>'.`
  - `Erro: Espaço insuficiente no disco simulado.`

---

### 2.4. `read_file`
- **Sintaxe:** `read_file <caminho_arquivo>`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`.
- **Parâmetros Opcionais:** `--hex` (exibir dump hexadecimal dos blocos).
- **Pré-condições:** Arquivo deve existir.
- **Permissões Necessárias:** Permissão de leitura (`r`) no arquivo.
- **Subsistema Responsável:** `security` $\to$ `filesystem` $\to$ `io`.
- **Resultado Esperado:** Exibição do conteúdo do arquivo, descriptografia automática caso protegido e log de auditoria.
- **Mensagens de Erro:**
  - `Erro: Permissão negada para leitura no arquivo '<caminho>'.`
  - `Erro: Arquivo '<caminho>' não encontrado.`

---

### 2.5. `fs_status`
- **Sintaxe:** `fs_status [--detailed]`
- **Parâmetros Obrigatórios:** Nenhum.
- **Parâmetros Opcionais:** `--detailed` (exibe o mapa de todos os blocos individuais).
- **Pré-condições:** Sistema de arquivos montado.
- **Permissões Necessárias:** Qualquer usuário autenticado.
- **Subsistema Responsável:** `filesystem`.
- **Resultado Esperado:** Relatório de capacidade total, blocos ocupados, blocos livres, i-nodes utilizados, taxa de fragmentação interna e externa acumulada.

---

### 2.6. `login`
- **Sintaxe:** `login <username>`
- **Parâmetros Obrigatórios:** `<username>`.
- **Parâmetros Opcionais:** Nenhum (senha solicitada via prompt seguro).
- **Pré-condições:** O usuário deve estar cadastrado na base do simulador.
- **Permissões Necessárias:** Nenhuma prévia.
- **Subsistema Responsável:** `security`.
- **Resultado Esperado:** Validação de PBKDF2 com salt, inicialização da sessão com as permissões do usuário e registro no `AuditLog`.
- **Mensagens de Erro:**
  - `Erro: Usuário '<username>' não encontrado.`
  - `Erro: Senha incorreta. Tentativa registrada no log de auditoria.`

---

### 2.7. `chmod`
- **Sintaxe:** `chmod <mascara_octal> <caminho>`
- **Parâmetros Obrigatórios:** `<mascara_octal>` (ex.: `750`, `644`), `<caminho>`.
- **Pré-condições:** O recurso deve existir.
- **Permissões Necessárias:** Proprietário do recurso ou `root`.
- **Subsistema Responsável:** `security` / `filesystem`.
- **Resultado Esperado:** Atualização da ACL no i-node e log de auditoria.
- **Mensagens de Erro:**
  - `Erro: Permissão negada. Somente o proprietário ou root pode alterar permissões.`
  - `Erro: Máscara octal inválida. Utilize valores entre 000 e 777.`

---

### 2.8. `encrypt_file`
- **Sintaxe:** `encrypt_file <caminho_arquivo>`
- **Parâmetros Obrigatórios:** `<caminho_arquivo>`.
- **Pré-condições:** Arquivo existente com conteúdo.
- **Permissões Necessárias:** Proprietário do arquivo ou `root`.
- **Subsistema Responsável:** `security` $\to$ `filesystem` $\to$ `io`.
- **Resultado Esperado:** Cifragem da carga dos blocos de dados, marcação da flag de criptografia no i-node e registro em auditoria.
- **Mensagens de Erro:**
  - `Erro: Permissão negada para criptografar o arquivo.`
  - `Erro: O arquivo já se encontra criptografado.`

---

### 2.9. `antivirus_scan`
- **Sintaxe:** `antivirus_scan [<caminho_base>]`
- **Parâmetros Opcionais:** `<caminho_base>` (padrão `/`).
- **Pré-condições:** Sistema de arquivos operacional.
- **Permissões Necessárias:** Privilégio de leitura ou `root`.
- **Subsistema Responsável:** `security`.
- **Resultado Esperado:** Varredura de integridade (SHA-256) e busca por assinaturas maliciosas simuladas, gerando relatório de auditoria.

---

### 2.10. `create_process`
- **Sintaxe:** `create_process <nome> <tamanho_kb> [--reserved]`
- **Parâmetros Obrigatórios:** `<nome>`, `<tamanho_kb>`.
- **Parâmetros Opcionais:** `--reserved` (alocar na área reservada contígua de Kernel/Drivers).
- **Pré-condições:** Memória suficiente disponível.
- **Permissões Necessárias:** Se `--reserved`, exige privilégio de `root`/Modo Kernel.
- **Subsistema Responsável:** `process` $\to$ `memory`.
- **Resultado Esperado:** Criação de PCB com PID atribuído e alocação na área reservada (segmento contíguo) ou na área paginada (Page Table).
- **Mensagens de Erro:**
  - `Erro: Permissão negada. Apenas Modo Kernel pode alocar na área reservada.`
  - `Erro: Memória insuficiente. Fragmentação externa impede alocação contígua (execute 'memory_compact').`

---

### 2.11. `terminate_process`
- **Sintaxe:** `terminate_process <pid>`
- **Parâmetros Obrigatórios:** `<pid>`.
- **Pré-condições:** O processo com o PID fornecido deve estar ativo (`READY` ou `RUNNING`).
- **Permissões Necessárias:** Proprietário do processo ou `root`.
- **Subsistema Responsável:** `process` $\to$ `memory`.
- **Resultado Esperado:** Liberação de todos os recursos de memória (segmentos, frames e slots de swap) e atualização do PCB para `TERMINATED`.
- **Mensagens de Erro:**
  - `Erro: Processo com PID <pid> inexistente.`

---

### 2.12. `memory_status`
- **Sintaxe:** `memory_status`
- **Subsistema Responsável:** `memory`.
- **Resultado Esperado:** Diagnóstico visual completo:
  - Área Reservada: Segmentos alocados, buracos livres e cálculo de fragmentação externa.
  - Área Dinâmica: Molduras totais, molduras livres, molduras ocupadas por processo.
  - Swap: Capacidade total de slots e slots ocupados.

---

### 2.13. `memory_compact`
- **Sintaxe:** `memory_compact`
- **Pré-condições:** Área reservada com segmentos desalocados intermediários (buracos).
- **Permissões Necessárias:** Privilégio de `root` / Modo Kernel.
- **Subsistema Responsável:** `memory`.
- **Resultado Esperado:** Reorganização deslizante de segmentos alocados, unificação de todos os buracos livres em um único segmento livre contíguo e relatório de fragmentação zerada.

---

### 2.14. `translate_address`
- **Sintaxe:** `translate_address <pid> <endereco_logico>`
- **Parâmetros Obrigatórios:** `<pid>`, `<endereco_logico>`.
- **Subsistema Responsável:** `memory` (MMU).
- **Resultado Esperado:** Decomposição em $(p, d)$, consulta à Page Table e tradução para o endereço físico $(f, d)$, ou notificação de Page Fault se a página não estiver presente na RAM física.

---

### 2.15. `execute_step`
- **Sintaxe:** `execute_step <pid> <endereco_logico>`
- **Parâmetros Obrigatórios:** `<pid>`, `<endereco_logico>`.
- **Subsistema Responsável:** `process` $\to$ `memory` $\to$ `io`.
- **Resultado Esperado:** Simulação de acesso a uma instrução de memória: tradução de endereço, tratamento de Page Fault sob demanda (se necessário), execução de política de substituição (LRU ou Segunda Chance) e carregamento via Swap.

---

## 3. EXEMPLOS OFICIAIS DE FORMATAÇÃO DE SAÍDAS

Abaixo constam os padrões visuais rigorosos a serem emitidos pela CLI para garantir conformidade acadêmica e aprovação nos testes determinísticos.

### 3.1. Saída do Comando `fs_status`
```text
======================================================================
                  DIAGNÓSTICO DO SISTEMA DE ARQUIVOS
======================================================================
Estratégia de Alocação Ativa : INDEXADA (i-node)
Tamanho do Bloco             : 4.096 bytes (4 KB)
Total de Blocos no Disco     : 1.024 blocos (4.096 KB)
Blocos Ocupados              : 32 blocos
Blocos Livres                : 992 blocos
Total de i-nodes             : 128 (Ocupados: 6 | Livres: 122)
----------------------------------------------------------------------
Fragmentação Interna Total   : 6.144 bytes
Fragmentação Externa Total   : 0 bytes (não aplicável à alocação indexada)
======================================================================
```

### 3.2. Saída do Comando `write_file` (Cenário FS-002)
```text
[write_file] Arquivo gravado com sucesso: /sistema/logs/app.log
Tamanho Real do Conteúdo   : 10.240 bytes (10,00 KB)
Blocos Físicos Alocados    : 3 blocos ([12, 13, 14])
Capacidade Total Alocada   : 12.288 bytes (12,00 KB)
Fragmentação Interna       : 2.048 bytes
Fragmentação Externa       : 0 bytes
```

### 3.3. Saída do Escalonador de Disco (Cenário IO-001 — SSTF)
```text
======================================================================
            RELATÓRIO DE ESCALONAMENTO DE DISCO (SSTF)
======================================================================
Posição Inicial do Cabeçote : Trilha 53
Fila de Requisições         : [98, 183, 37, 122, 14]
Ordem de Atendimento        : 53 -> 37 -> 14 -> 98 -> 122 -> 183
----------------------------------------------------------------------
Deslocamentos Detalhados:
  | 53 - 37 | = 16 trilhas
  | 37 - 14 | = 23 trilhas
  | 14 - 98 | = 84 trilhas
  | 98 - 122| = 24 trilhas
  | 122- 183| = 61 trilhas
----------------------------------------------------------------------
Movimentação Total do Braço : 208 trilhas
======================================================================
```

### 3.4. Saída de Falha e Reconstrução RAID 5 (Cenário IO-002)
```text
[RAID-5] Alerta: Falha física detectada no Disco 2!
[RAID-5] Modo de Operação: DEGRADADO
[RAID-5] Iniciando leitura com reconstrução em tempo real...
  Lendo Bloco 0 (Disco 1)     : [0x41, 0x42, 0x43, 0x44]
  Lendo Paridade (Disco 3)    : [0x05, 0x06, 0x07, 0x08]
  Reconstruindo Bloco 1 (D2)  : Bloco 0 ^ Paridade = [0x44, 0x44, 0x44, 0x4C]
[RAID-5] Bloco ausente recuperado com sucesso via XOR!
```

### 3.5. Saída de Negação de Acesso (Cenário SEC-002)
```text
[ERRO DE SEGURANÇA] Acesso Negado!
Recurso Solicitado : /sistema/config.sys
Usuário Ativo      : carlos (Grupos: devs)
Proprietário/Grupo : root:admin
Permissões do Nó   : -rwxr-x--- (750)
Ação Solicitada    : LEITURA (r)
Motivo             : Usuário 'carlos' não é proprietário, não pertence ao grupo 'admin' e as permissões para 'outros' são nulas (---).
Auditoria          : Evento #1042 gravado com sucesso em /var/log/audit.log.
```

### 3.6. Saída do Diagnóstico de Memória e Compactação (Cenários MEM-001 e MEM-002)
```text
======================================================================
              DIAGNÓSTICO DA ÁREA DE MEMÓRIA RESERVADA
======================================================================
Capacidade Total Reservada  : 4.096 KB (4 MB)
Segmentos Atuais:
  [0000 - 1023 KB] : Nucleo_Base (1.024 KB) - OCUPADO
  [1024 - 1535 KB] : Kernel_DiskDriver (512 KB) - OCUPADO
  [1536 - 2559 KB] : [BURACO LIVRE] (1.024 KB) - LIVRE
  [2560 - 3071 KB] : Kernel_CryptoEngine (512 KB) - OCUPADO
  [3072 - 4095 KB] : [BURACO LIVRE] (1.024 KB) - LIVRE
----------------------------------------------------------------------
Espaço Livre Total          : 2.048 KB
Maior Bloco Livre Contíguo  : 1.024 KB
Fragmentação Externa        : 1.024 KB (impede alocação contígua de 1.536 KB!)
======================================================================

[Ação: memory_compact executado pelo usuário root]

======================================================================
        ÁREA DE MEMÓRIA RESERVADA APÓS COMPACTAÇÃO DESLIZANTE
======================================================================
Segmentos Reorganizados:
  [0000 - 1023 KB] : Nucleo_Base (1.024 KB) - OCUPADO
  [1024 - 1535 KB] : Kernel_DiskDriver (512 KB) - OCUPADO
  [1536 - 2047 KB] : Kernel_CryptoEngine (512 KB) - OCUPADO
  [2048 - 4095 KB] : [BLOCO LIVRE CONSOLIDADO] (2.048 KB) - LIVRE
----------------------------------------------------------------------
Fragmentação Externa        : 0 KB (Capacidade máxima contígua: 2.048 KB)
======================================================================
```
