#!/usr/bin/env python3
"""
Seed script for PRAG public demo documents.
Generates and pre-indexes the 2 reference demonstration documents:
1. Contrato de Prestação de Serviços Cloud & SLA (8 páginas)
2. Manual do Colaborador & Política Interna (12 páginas)

All demo documents are seeded with `is_demo = True` and `session_id = None`,
enabling immediate question-answering without requiring user uploads.

Usage:
    python scripts/seed_demo.py [--force]
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
import pymupdf
import structlog
from sqlalchemy import delete, select

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.db.models import Chunk, Document
from app.db.session import async_session_maker
from app.ingestion.chunker import create_chunks_from_pages
from app.ingestion.embeddings import generate_embeddings_batch
from app.ingestion.extract import extract_pages_with_words
from app.services.storage import save_file

logger = structlog.get_logger()

EVAL_DATASET_PATH = (
    backend_dir / "app" / "evals" / "datasets" / "nexus_cloud_contract.json"
)


def generate_contract_pdf(target_path: str) -> None:
    """Generates the 8-page Nexus Cloud Contract PDF from the evals dataset."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(EVAL_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = data["document"]["pages"]
    doc = pymupdf.open()
    for p in pages:
        page = doc.new_page(width=595, height=842)  # A4
        rect = pymupdf.Rect(50, 60, 545, 780)
        page.insert_textbox(rect, p["content"], fontsize=10.5, fontname="helv")
    doc.save(target_path)
    doc.close()


def generate_employee_handbook_pdf(target_path: str) -> None:
    """Generates a realistic 12-page Employee Handbook & Internal Policies PDF."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    handbook_pages = [
        # Página 1
        """INNOVATECH SOLUTIONS, LDA.
MANUAL DO COLABORADOR E POLÍTICA INTERNA DE GESTÃO
Versão 2.4 — Documento Corporativo de Consulta Obrigatória

CAPÍTULO 1: INTRODUÇÃO E CULTURA ORGANIZACIONAL

1.1 Boas-vindas à Innovatech Solutions
A Innovatech Solutions, Lda. (adiante designada abreviadamente por 'Empresa') foi fundada com o propósito fundamental de desenvolver tecnologias de vanguarda no ecossistema europeu de engenharia de software e inteligência artificial. Este Manual do Colaborador estabelece as diretrizes profissionais, direitos, benefícios e deveres que regem a relação de trabalho entre a Empresa e os seus colaboradores.

1.2 Missão, Visão e Valores
A nossa Missão consiste em entregar soluções digitais altamente confiáveis, transparentes e auditáveis, operando na fronteira da precisão técnica. A nossa Visão é liderar o mercado ibérico como referência incontestável em engenharia de sistemas seguros e confiabilidade algorítmica até ao ano de 2028.

Os nossos Valores fundamentais são:
1. Rigor e Excelência Técnica: a integridade e a qualidade do código são inegociáveis.
2. Honestidade Intelectual e Transparência: comunicamos factos de forma objetiva e sem subterfúgios.
3. Colaboração Empática e Respeitosa: o trabalho em equipa assenta no respeito mútuo e na escuta ativa.
4. Inovação Responsável: promovemos a experimentação ética e sustentável de novas abordagens computacionais.
5. Foco no Impacto e no Cliente: criamos valor tangível e mensurável através da simplificação de problemas complexos.""",

        # Página 2
        """CAPÍTULO 2: MODELO DE TRABALHO, EQUIPAMENTO E APOIO AO TELETRABALHO

2.1 Modelo Híbrido Flexível
A Innovatech adota preferencialmente o regime de trabalho híbrido, combinando a colaboração presencial nos escritórios centrais (Avenida da Liberdade, Lisboa) com o teletrabalho a partir da residência habitual do colaborador. Os membros da equipa técnica devem comparecer presencialmente um mínimo de 2 (dois) dias por semana, a combinar com a respetiva liderança de equipa.

2.2 Equipamento Fornecido pela Empresa
No primeiro dia de integração profissional, a Empresa disponibiliza a cada colaborador:
a) 1 computador portátil de gama profissional (MacBook Pro 16" ou Dell XPS 15, consoante perfil técnico);
b) 2 monitores externos 4K de 27 polegadas para a estação de trabalho;
c) 1 conjunto de auscultadores com cancelamento de ruído ativo (ANC);
d) 1 chave de segurança de hardware (FIDO2/WebAuthn) para autenticação nos sistemas internos.

Todo o equipamento informático permanece propriedade exclusiva da Innovatech Solutions e destina-se primordialmente a fins profissionais.

2.3 Subsídio e Compensação Financeira de Teletrabalho
Em conformidade com a legislação laboral aplicável, a Empresa atribui uma compensação financeira fixa no montante mensal de 35,00 EUR (trinta e cinco euros), isenta de encargos sociais, destinada a comparticipar os custos acrescidos de eletricidade e serviço de acesso à internet de banda larga em ambiente doméstico.""",

        # Página 3
        """CAPÍTULO 3: HORÁRIOS, FLEXIBILIDADE E REGISTO DE ASSIDUIDADE

3.1 Horário Normal de Trabalho
O período normal de trabalho semanal é de 40 (quarenta) horas, distribuídas de segunda a sexta-feira, correspondendo a 8 (oito) horas diárias de trabalho efetivo, intercaladas com um período de intervalo de descanso de duração não inferior a 1 (uma) hora nem superior a 2 (duas) horas.

3.2 Margem de Flexibilidade e Horas de Contacto Obrigatório (Core Hours)
Para promover a conciliação entre a vida profissional, familiar e pessoal, a Empresa admite horários de entrada flexíveis entre as 08:00 e as 10:00 da manhã, e de saída correspondente entre as 17:00 e as 19:00.
Todavia, todos os colaboradores devem estar integralmente contactáveis e disponíveis para reuniões síncronas durante a janela de horas de contacto obrigatório (Core Hours), fixada rigorosamente entre as 10:30 e as 12:30 e entre as 14:30 e as 16:30.

3.3 Banco de Horas e Trabalho Suplementar
A prestação de trabalho suplementar carece de prévia autorização escrita da Direção de Operações. Quando indispensável e autorizada, cada hora extraordinária prestada além do período normal é creditada no banco de horas individual na proporção de 1,5 horas de descanso compensatório por cada hora de trabalho em dias úteis, ou 2,0 horas em dias de descanso semanal e feriados obrigatórios.

3.4 Registo Digital de Assiduidade
O registo diário de assiduidade e pausas é efetuado através da plataforma interna de gestão de talento (WorkPortal), garantindo o cumprimento dos imperativos legais do Código do Trabalho.""",

        # Página 4
        """CAPÍTULO 4: POLÍTICA DE FÉRIAS, FALTAS E AUSÊNCIAS

4.1 Direito a Férias e Majoração por Assiduidade
O período anual de férias remuneradas é de 22 (vinte e dois) dias úteis base, vencendo-se a 1 de janeiro de cada ano civil com reporte ao trabalho prestado no ano antecedente.
A Empresa premeia o empenho e regularidade: os colaboradores que não tenham registado faltas injustificadas ao longo do ano civil anterior beneficiam de uma majoração extraordinária de até 3 (três) dias úteis adicionais de férias, perfazendo um total máximo de 25 dias úteis de descanso anual remunerado.

4.2 Prazos e Procedimento de Marcação de Férias
O mapa provisório de marcação de férias para o ano em curso deve ser submetido impreterivelmente até ao dia 31 de março através do WorkPortal. O plano final é validado pelas chefias diretas e afixado até ao dia 15 de abril de cada ano.
Recomenda-se o gozo de pelo menos um período contínuo de 10 (dez) dias úteis consecutivos durante os meses de época estival (entre 1 de junho e 30 de setembro).

4.3 Comunicação e Justificação de Ausências e Faltas
Qualquer ausência ou impedimento imprevisto deve ser notificado à respetiva chefia e aos Recursos Humanos por correio eletrónico com a maior antecedência viável, e no máximo até 2 horas após a hora habitual de entrada.
A apresentação do correspondente comprovativo legal (ex.: declaração hospitalar de internamento ou baixa médica por incapacidade temporária emitida pelo SNS) deve ocorrer no prazo impreterível de 5 (cinco) dias úteis a contar do primeiro dia de ausência.""",

        # Página 5
        """CAPÍTULO 5: CÓDIGO DE CONDUTA, ÉTICA E PREVENÇÃO DO ASSÉDIO

5.1 Padrão de Conduta e Relacionamento Interpessoal
A Innovatech exige que todas as relações profissionais sejam pautadas pelo mais estrito respeito pela dignidade humana, camaradagem, cortesia e urbanidade. Não é tolerada qualquer linguagem agressiva, depreciativa, humilhante ou discriminatória em nenhum canal de comunicação interno (incluindo Slack, e-mails ou reuniões por videoconferência).

5.2 Política de Tolerância Zero ao Assédio
A Empresa adota uma política categórica de Tolerância Zero a qualquer forma de assédio moral, assédio sexual ou intimidação (bullying) no ambiente de trabalho. Entende-se por assédio todo o comportamento indesejado baseado em fatores como género, orientação sexual, raça, etnia, idade, religião ou convicções políticas, que tenha por objetivo ou efeito afetar a dignidade da pessoa ou criar um ambiente intimidatório, hostil, degradante ou desestabilizador.

5.3 Prevenção de Conflitos de Interesses
Os colaboradores não podem exercer, direta ou indiretamente, atividades paralelas que colidam ou concorram com a atividade da Empresa, nem prestar consultoria remunerada a clientes ou concorrentes diretos da Innovatech sem prévia autorização formal escrita do Conselho de Administração.

5.4 Ofertas e Hospitalidade Comercial
É expressamente proibido aos colaboradores aceitar presentes, favores ou vantagens financeiras de clientes, parceiros ou fornecedores cujo valor individual estimado exceda o montante de 50,00 EUR (cinquenta euros). Qualquer oferta que ultrapasse este limiar deve ser de pronto reportada ao Departamento de Compliance e entregue para sorteio de caridade da Empresa.""",

        # Página 6
        """CAPÍTULO 6: SEGURANÇA DA INFORMAÇÃO E POLÍTICA DE CREDENCIAIS

6.1 Importância Crítica da Segurança
Operando em sistemas de missão crítica, a segurança dos dados e das infraestruturas é uma responsabilidade prioritária de cada colaborador. A violação negligente ou deliberada de diretrizes de cibersegurança constitui infração disciplinar grave.

6.2 Requisitos de Palavras-passe e Credenciais
Todas as contas corporativas devem seguir imperativamente os seguintes critérios de robustez:
a) Comprimento mínimo de 14 (catorze) caracteres alfanuméricos;
b) Inclusão obrigatória de letras maiúsculas, minúsculas, algarismos numéricos e símbolos especiais (ex.: !@#$%&*);
c) Renovação obrigatória da palavra-passe mestre a cada 90 (noventa) dias;
d) Proibição absoluta de reutilização das últimas 6 (seis) palavras-passe;
e) Utilização obrigatória de um gestor de palavras-passe empresarial aprovado pela equipa de Segurança (1Password ou Bitwarden Enterprise).

6.3 Autenticação Multifator (MFA) Obrigatória
O recurso a autenticação multifator (MFA) é compulsório para acesso a qualquer plataforma, repositório de código, consola cloud (AWS, GCP, Cloudflare) ou caixa de correio eletrónico. A autenticação por SMS é proibida por motivos de vulnerabilidade a SIM swapping, sendo exigida a utilização de geradores TOTP ou chaves físicas de segurança FIDO2.

6.4 Proibição de Partilha de Contas e Credenciais
As contas de utilizador são estritamente pessoais e intransmissíveis. A partilha voluntária de credenciais, chaves privadas SSH ou tokens de acesso API entre colegas ou com terceiros é estritamente proibida.""",

        # Página 7
        """CAPÍTULO 7: PROTEÇÃO DE DADOS PESSOAIS (RGPD) E CLASSIFICAÇÃO

7.1 Compromisso com o Regulamento Geral sobre a Proteção de Dados (RGPD)
A Empresa atua em estrita conformidade com o Regulamento (UE) 2016/679 (RGPD) e a Lei n.º 58/2019. Todos os colaboradores que tenham acesso a dados pessoais de clientes, fornecedores ou outros trabalhadores devem observar escrupulosamente os princípios de licitude, lealdade, transparência, limitação das finalidades, minimização dos dados e confidencialidade.

7.2 Níveis de Classificação da Informação
Todos os ficheiros, bases de dados e repositórios internos da Empresa são categorizados em quatro níveis de confidencialidade:
1. Pública (Public): informação divulgada abertamente no website ou comunicados de imprensa institucionais.
2. Uso Interno (Internal): documentação padrão de processos, diretrizes e comunicações gerais destinadas à equipa.
3. Confidencial (Confidential): código-fonte de produtos, arquiteturas técnicas de software, contratos com clientes, dados financeiros e planos de negócio não públicos.
4. Estritamente Secreta (Restricted): credenciais de infraestrutura de produção, chaves criptográficas privadas, dados sensíveis de RH e dados pessoais de categoria especial.

7.3 Tratamento de Incidentes de Violação de Dados
Qualquer suspeita ou evidência concreta de fuga, perda acidental, acesso não autorizado ou destruição de dados pessoais deve ser comunicada de imediato (e nunca além de 2 horas após a deteção) ao Encarregado da Proteção de Dados (DPO) através do e-mail: dpo@innovatech.example.com.""",

        # Página 8
        """CAPÍTULO 8: UTILIZAÇÃO RESPONSÁVEL DE INTELIGÊNCIA ARTIFICIAL E CLOUD

8.1 Enquadramento do Uso de Ferramentas de IA
A Innovatech encoraja a experimentação produtiva de assistentes de inteligência artificial e modelos generativos para apoio ao desenvolvimento de software, redação técnica e análise exploratória, desde que observadas regras estritas de proteção de propriedade intelectual.

8.2 Proibições Estritas no Uso de Modelos Públicos
É terminantemente proibido inserir, carregar ou submeter em interfaces web ou APIs de serviços de IA públicos e genéricos (ex.: ChatGPT gratuito, Claude web sem subscrição empresarial, Gemini público):
a) Ficheiros completos ou excertos de código-fonte proprietário da Empresa;
b) Dados pessoais identificáveis de colaboradores, candidatos ou utilizadores finais;
c) Documentos contratuais de clientes, propostas comerciais ou detalhes confidenciais de SLAs;
d) Chaves criptográficas, certificados digitais, senhas ou tokens de autenticação.

8.3 Ferramentas de IA Homologadas
Os colaboradores devem recorrer unicamente às subscrições corporativas provisionadas pela Empresa (GitHub Copilot for Business e contas empresariais com cláusula de não-retenção de dados para treino).

8.4 Auditoria e Verificação de Código Gerado por IA
Qualquer código-fonte ou documentação gerada com auxílio de modelos de linguagem é da inteira responsabilidade do colaborador que o subscreve, devendo ser submetido aos processos regulares de revisão por pares (Code Review), testes unitários e validação de segurança antes de ser integrado na ramificação principal.""",

        # Página 9
        """CAPÍTULO 9: POLÍTICA DE DESPESAS, VIAGENS E SUBSÍDIO DE REFEIÇÃO

9.1 Cartão e Subsídio de Refeição
A Empresa paga o subsídio de refeição sob a forma de cartão eletrónico de refeição pré-pago no montante de 9,60 EUR (nove euros e sessenta cêntimos) por cada dia útil de trabalho efetivo, usufruindo da isenção máxima permitida por lei para efeitos de IRS e Segurança Social.

9.2 Despesas de Deslocação e Viagens de Trabalho
Quando em serviço externo formalmente solicitado, as despesas de transporte são reembolsadas nos seguintes moldes:
a) Utilização de viatura própria: compensação quilométrica no valor de 0,40 EUR por quilómetro percorrido, acrescido do reembolso integral de portagens e parques de estacionamento;
b) Transportes públicos e comboio: classe turística para viagens nacionais;
c) Viagens aéreas internacionais: voos em classe económica para durações inferiores a 6 horas de voo contínuo.

9.3 Limites para Refeições em Viagem e Representação
Para refeições em contexto de deslocação profissional ou representação institucional com clientes, vigoram os seguintes limites máximos por pessoa (incluindo IVA):
- Almoço de trabalho individual: até 25,00 EUR;
- Jantar de trabalho individual: até 35,00 EUR;
- Jantar de representação comercial com clientes (previamente autorizado): até 45,00 EUR por participante.

9.4 Submissão de Faturas e Reembolso
Todas as faturas devem conter obrigatoriamente o NIF da Empresa (509 999 999) e ser submetidas através do módulo de despesas do WorkPortal até ao dia 20 de cada mês para liquidação no processamento salarial do mês corrente.""",

        # Página 10
        """CAPÍTULO 10: BENEFÍCIOS CORPORATIVOS, SAÚDE E FORMAÇÃO

10.1 Plano de Seguro de Saúde Coletivo
A Innovatech proporciona a todos os colaboradores com contrato de trabalho a termo ou por tempo indeterminado um Seguro de Saúde de cobertura alargada (Plano Advance Care / Multicare), com as seguintes características:
- Cobertura de hospitalização e cirurgia até ao limite de 100.000 EUR anuais;
- Cobertura de consultas de especialidade médica e ambulatório com copagamento de apenas 15,00 EUR por consulta na rede convencionada;
- Inclusão facultativa de cônjuges e filhos com condições de adesão corporativa vantajosas suportadas em 50% pela Empresa para descendentes menores.

10.2 Apoio à Saúde Mental e Bem-Estar
Reconhecendo a importância crucial do equilíbrio psicológico, a Empresa oferece 6 (seis) sessões anuais de consulta de psicologia clínica ou apoio emocional totalmente gratuitas, asseguradas de forma estritamente anónima e confidencial por entidade externa especializada.

10.3 Orçamento Individual para Formação e Certificações (Learning Budget)
Cada colaborador dispõe de um orçamento anual individual para desenvolvimento de competências no montante fixo de 1.200,00 EUR (mil e duzentos euros) por ano civil. Este valor pode ser afeto a:
a) Inscrição em conferências técnicas nacionais ou internacionais (online ou presenciais);
b) Cursos certificados em plataformas educativas de renome (Coursera, Udemy, etc.);
c) Exames de certificação oficial (ex.: certificações cloud AWS/GCP, Kubernetes CKA/CKAD, segurança OSCP).""",

        # Página 11
        """CAPÍTULO 11: AVALIAÇÃO DE DESEMPENHO E PROGRESSÃO DE CARREIRA

11.1 Metodologia de Objetivos e Resultados-Chave (OKRs)
A gestão estratégica e o acompanhamento de metas na Innovatech baseiam-se no modelo de OKRs (Objectives and Key Results), com ciclos trimestrais de definição, alinhamento e avaliação.
No início de cada trimestre (janeiro, abril, julho e outubro), cada colaborador alinha com a sua liderança direta de 3 a 5 resultados-chave mensuráveis, transparentes e articulados com as prioridades estratégicas da Empresa.

11.2 Ciclo Anual de Avaliação de Desempenho e Revisão Salarial
O processo global de avaliação ocorre uma vez por ano, decorrendo formalmente entre 15 de novembro e 15 de dezembro. O ciclo é composto por:
1. Autoavaliação reflexiva do próprio colaborador;
2. Avaliação por pares em 360 graus (mínimo de 3 colegas indicados mutuamente);
3. Avaliação de competências técnicas e comportamentais pelo gestor de equipa;
4. Sessão formal síncrona de calibração e feedback de desenvolvimento de carreira.

11.3 Tabela Salarial e Critérios de Progressão
A progressão de nível de carreira (de Júnior para Pleno, Pleno para Sénior, e Sénior para Principal/Staff Engineer) segue uma matriz de competências pública e auditável, disponível na wiki interna. A progressão salarial não depende de antiguidade mecânica, mas sim da demonstração comprovada e consistente de autonomia técnica, impacto arquitetural e mentoria positiva dos pares.""",

        # Página 12
        """CAPÍTULO 12: CANAL ÉTICO DE DENÚNCIA ANÓNIMA, DISCIPLINA E CONTACTOS

12.1 Canal de Denúncias Interno (Whistleblowing)
Em cumprimento da Lei n.º 93/2021 sobre a proteção de denunciantes de infrações, a Innovatech disponibiliza um Canal de Denúncias seguro e auditado externamente, acessível 24 horas por dia em:
https://ethics.innovatech.example.com
O canal permite a submissão de relatos totalmente anónimos relativos a irregularidades financeiras, assédio, corrupção, quebras graves de segurança informática ou violações da legislação vigente. É garantida por lei a proibição absoluta de qualquer ato de retaliação contra o denunciante de boa-fé.

12.2 Procedimento Disciplinar e Sanções Aplicáveis
O incumprimento doloso ou negligente dos deveres plasmados neste Manual sujeita o infrator a procedimento disciplinar instruído ao abrigo do Código do Trabalho. As sanções disciplinares, graduadas em função da gravidade da infração e da culpa do agente, compreendem:
a) Repreensão simples verbal ou escrita;
b) Sanção pecuniária até ao limite de 1/3 da remuneração diária;
c) Perda temporária de dias de férias até ao máximo de 3 dias úteis;
d) Suspensão do trabalho com perda de retribuição e de antiguidade (até 30 dias);
e) Despedimento com justa causa sem indemnização nem compensação.

12.3 Contactos de Suporte e Apoio Interno
- Direção de Recursos Humanos (People Team): people@innovatech.example.com
- Apoio a Benefícios e Férias: benefits@innovatech.example.com
- Encarregado de Proteção de Dados (DPO): dpo@innovatech.example.com
- Suporte Técnico e Helpdesk de TI: support@innovatech.example.com
- Contacto Telefónico Geral da Sede: +351 210 000 000 (dias úteis das 09:00 às 18:00)

Lisboa, Janeiro de 2026 — Conselho de Administração da Innovatech Solutions, Lda.""",
    ]

    doc = pymupdf.open()
    for content in handbook_pages:
        page = doc.new_page(width=595, height=842)  # A4
        rect = pymupdf.Rect(50, 60, 545, 780)
        page.insert_textbox(rect, content, fontsize=9.5, fontname="helv")
    doc.save(target_path)
    doc.close()


async def seed_single_document(
    filename: str,
    generate_fn,
    force: bool = False,
) -> Document:
    """Idempotently seeds and indexes a demo document."""
    async with async_session_maker() as db:
        stmt = select(Document).where(
            Document.filename == filename,
            Document.is_demo.is_(True),
        )
        res = await db.execute(stmt)
        existing_doc = res.scalars().first()

        if existing_doc and not force:
            # Check if chunks already exist
            count_stmt = select(Chunk).where(Chunk.document_id == existing_doc.id)
            c_res = await db.execute(count_stmt)
            existing_chunks = c_res.scalars().all()
            if existing_chunks:
                logger.info(
                    "demo_document_already_seeded",
                    filename=filename,
                    document_id=str(existing_doc.id),
                    chunks=len(existing_chunks),
                )
                return existing_doc

    # Temporary generation path
    storage_dir = Path(settings.STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    temp_pdf_path = str(storage_dir / f"temp_{filename}")
    generate_fn(temp_pdf_path)

    with open(temp_pdf_path, "rb") as f:
        file_bytes = f.read()
        sha256 = hashlib.sha256(file_bytes).hexdigest()

    async with async_session_maker() as db:
        if existing_doc:
            doc = existing_doc
            # Remove old chunks
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        else:
            doc_id = uuid.uuid4()
            storage_key = await save_file(str(doc_id), file_bytes)

            doc = Document(
                id=doc_id,
                session_id=None,
                filename=filename,
                sha256=sha256,
                storage_key=storage_key,
                page_count=0,
                status="processing",
                is_demo=True,
            )
            db.add(doc)
            await db.flush()

        # Extract pages with word bboxes
        pages = extract_pages_with_words(temp_pdf_path)
        doc.page_count = len(pages)

        # Chunk with max 2 pages invariant
        chunks_data = create_chunks_from_pages(pages, target_words=180, overlap_words=25)

        logger.info(
            "indexing_demo_document",
            filename=filename,
            pages=len(pages),
            chunks=len(chunks_data),
        )

        # Generate embeddings in batches of 10
        batch_size = 10
        for i in range(0, len(chunks_data), batch_size):
            batch = chunks_data[i : i + batch_size]
            batch_texts = [c["text"] for c in batch]
            embeddings = await generate_embeddings_batch(batch_texts, task_type="RETRIEVAL_DOCUMENT")

            for chunk_info, emb in zip(batch, embeddings):
                chunk_obj = Chunk(
                    document_id=doc.id,
                    chunk_index=chunk_info["chunk_index"],
                    page_start=chunk_info["page_start"],
                    page_end=chunk_info["page_end"],
                    text=chunk_info["text"],
                    bboxes=chunk_info["bboxes"],
                    embedding=emb,
                    embedding_model=settings.EMBED_MODEL,
                    embedding_dim=settings.EMBED_DIM,
                )
                db.add(chunk_obj)

        doc.status = "ready"
        await db.commit()

        # Clean temp file
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

        logger.info(
            "demo_document_seeded_successfully",
            filename=filename,
            document_id=str(doc.id),
            chunks=len(chunks_data),
        )
        return doc


async def main():
    parser = argparse.ArgumentParser(description="Seed demo documents for PRAG")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-generation and re-indexing of demo documents even if already present",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  PRAG: SEEDING DEMONSTRATION DOCUMENTS")
    print(f"  Embed Model: {settings.EMBED_MODEL} ({settings.EMBED_DIM}d) | Force: {args.force}")
    print("=" * 70)

    # 1. Seed Contract PDF (~8 pages)
    print("\n[1/2] Seeding 'Contrato de Prestação de Serviços Cloud & SLA'...")
    doc1 = await seed_single_document(
        filename="nexus_cloud_contract.pdf",
        generate_fn=generate_contract_pdf,
        force=args.force,
    )
    print(f"      ✓ ID: {doc1.id} | Status: {doc1.status} | Páginas: {doc1.page_count}")

    # 2. Seed Employee Handbook PDF (~12 pages)
    print("\n[2/2] Seeding 'Manual do Colaborador & Política Interna'...")
    doc2 = await seed_single_document(
        filename="manual_do_colaborador.pdf",
        generate_fn=generate_employee_handbook_pdf,
        force=args.force,
    )
    print(f"      ✓ ID: {doc2.id} | Status: {doc2.status} | Páginas: {doc2.page_count}")

    print("\n" + "=" * 70)
    print("  DEMO DOCUMENTS SEEDED AND READY!")
    print("  Visitors can immediately ask questions without uploading files.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
