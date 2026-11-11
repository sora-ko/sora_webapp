"""公開仕様・架空画面だけから、中間発表用PPTX/PDFと発表原稿をローカル生成する。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import pypdfium2


ROOT = Path(__file__).resolve().parent
W, H = 1280, 720
COLORS = dict(bg='F4F7F5', white='FFFFFF', ink='20382F', green='24674F', mint='E3F0E8',
              muted='61746B', line='D9E4DD', amber='8B5D20', sand='FFF3DA', blue='315D79',
              pale_blue='E7F0F6', red='934E42')
FONT_DIR = Path(os.environ.get('CREDIT_SLIDE_FONT_DIR', 'C:/Windows/Fonts'))
pdfmetrics.registerFont(TTFont('Meiryo', str(FONT_DIR / 'meiryo.ttc'), subfontIndex=0))
pdfmetrics.registerFont(TTFont('MeiryoBold', str(FONT_DIR / 'meiryob.ttc'), subfontIndex=0))


@dataclass
class Slide:
    title: str
    section: str
    seconds: int
    note: str
    source: str
    appendix: bool = False
    items: list = field(default_factory=list)

    def box(self, x, y, w, h, fill='white', radius=14, line=None):
        self.items.append(dict(kind='box', x=x, y=y, w=w, h=h, fill=COLORS.get(fill, fill),
                               radius=radius, line=COLORS.get(line, line) if line else None))

    def text(self, x, y, w, h, value, size=24, color='ink', bold=False, align='left', wrap=True):
        font = 'MeiryoBold' if bold else 'Meiryo'
        lines = []
        for original in value.split('\n'):
            if not wrap:
                lines.append(original)
                continue
            line = ''
            for char in original:
                if line and pdfmetrics.stringWidth(line + char, font, size) > w - 2:
                    if char in '、。，．？！）」』】' and len(line) > 1:
                        lines.append(line[:-1]); line = line[-1] + char
                    else:
                        lines.append(line); line = char
                else:
                    line += char
            lines.append(line)
        leading = size * 1.48
        natural = size * 1.25 + leading * (len(lines) - 1)
        if natural > h + 1:
            raise ValueError(f'Text height exceeds frame on {self.title}: {value[:25]} ({natural:.1f}>{h})')
        self.items.append(dict(kind='text', x=x, y=y, w=w, h=h, text='\n'.join(lines),
                               size=size, color=COLORS.get(color, color), bold=bold, align=align,
                               leading=leading))

    def image(self, file, x, y, w, h):
        path = ROOT / 'assets' / file
        with Image.open(path) as image:
            iw, ih = image.size
        factor = min(w / iw, h / ih)
        dw, dh = iw * factor, ih * factor
        self.items.append(dict(kind='image', file='assets/' + file, x=x + (w-dw)/2,
                               y=y + (h-dh)/2, w=dw, h=dh))

    def heading(self, subtitle=''):
        self.text(64, 34, 1000, 28, self.section, 16, 'green', True)
        self.text(64, 84, 1160, 70, self.title, 36, bold=True)
        if subtitle:
            self.text(66, 154, 1150, 60, subtitle, 21, 'muted')

    def card(self, x, y, w, h, kicker, title, body, fill='white'):
        self.box(x, y, w, h, fill, line='line')
        self.text(x+24, y+24, w-48, 28, kicker, 17, 'green', True)
        self.text(x+24, y+68, w-48, 78, title, 27, bold=True)
        self.text(x+24, y+160, w-48, h-176, body, 22, 'muted')


slides: list[Slide] = []


def new(title, section, seconds, note, source, appendix=False):
    slide = Slide(title, section, seconds, textwrap.dedent(note).strip(), source, appendix)
    slides.append(slide)
    return slide


s = new('単位ノート', '情報システム基礎実習｜中間発表', 30, '''
    私たちが作っているのは、成績CSVから単位の状況を確認し、次に取る教養科目まで探せるWebアプリ「単位ノート」です。
    現在は新潟大学工学部・知能情報システムプログラムの2025年度入学者を対象にしています。
    今日は、必要な機能をどう決め、どんなデータとロジックで動かし、どこまで検証できたかを説明します。
    ''', 'docs/requirements.md §2–4; docs/handoff.md §1')
s.box(840, 0, 440, 720, 'green', 0)
s.text(70, 58, 720, 30, s.section, 19, 'green', True)
s.text(66, 178, 720, 100, '単位ノート', 76, bold=True)
s.text(72, 307, 690, 120, '修得単位の確認から、\n次の履修候補まで。', 37, bold=True)
s.text(74, 482, 670, 85, '新潟大学 工学部\n知能情報システムプログラム・2025年度入学', 22, 'muted')
s.text(74, 630, 690, 35, '2026.10.28  /  実装・テストまでの進捗', 18, 'muted')
for y, title, sub in [(170, '見える', '修得状況と必要な条件'), (330, 'わかる', '不足・要確認の理由'), (490, '探せる', '空き時間の教養候補')]:
    s.text(895, y, 310, 65, title, 48, 'white', True)
    s.text(897, y+78, 320, 38, sub, 22, 'mint')

s = new('「合計」だけでは、次の履修を決めにくい', '01  誰の、どんな課題を解くか', 50, '''
    想定利用者は、知能情報システムプログラムで進級や卒業までの見通しを知りたい学生本人です。
    特に、2025年度入学の2年生を基準にしています。大学から成績CSVを取得できることが前提です。
    合計の単位数を数えるだけでは、必修の取り残しや、どの区分が不足しているかまでは分かりません。
    さらに次の授業を選ぶには、履修表と開講情報を見比べる必要があります。
    そこで、取得したCSVを入力するだけで、現在地、不足の理由、次の候補をつなげて確認できることを目標にしました。
    これは現時点の想定ペルソナであり、学生への体系的な利用者調査を終えたという意味ではありません。
    ''', 'docs/requirements.md §2–3')
s.heading('想定ペルソナ：進級・卒業までの見通しを知りたい学生本人')
s.box(64, 242, 344, 350, 'green')
s.text(88, 269, 296, 36, '基準となる利用者', 21, 'mint', True)
s.text(88, 335, 296, 120, '知能情報の\n2年生', 40, 'white', True)
s.text(88, 469, 296, 85, '大学のCSVを持っている\n自分のPCで使いたい', 23, 'white')
for x, n, title, body in [(442,'1','区分が複雑','必修・選択必修・選択を\n自分で照合する'),(832,'2','次の行動が必要','不足する区分と\n空き時間を結び付けたい')]:
    s.box(x,242,360,350,line='line')
    s.text(x+25,269,300,46,n,34,'green',True)
    s.text(x+25,342,310,52,title,28,bold=True)
    s.text(x+25,432,310,112,body,24,'muted')
s.text(66, 620, 1150, 35, '目標：CSVから「現在地 → 必要なこと → 次の授業」まで見通せる', 24, 'green', True)

s = new('MVPで欠かせない3つの機能', '02  要件定義｜入力と出力', 55, '''
    最初の優先事項は、フロントからCSVを送り、Pythonで解析し、結果を画面に返すことでした。
    現在の機能セットは、次の三つに整理できます。一つ目は、成績CSVから修得済みの単位を区分別に表示すること。
    二つ目は、入学年度とプログラムの規則を使い、進級・卒業の参考判定と不足理由を表示すること。
    三つ目は、履修表と公開の開講情報を使い、時間を指定した教養候補と、不足を補う空き時間の候補を探すことです。
    成績分析や予測、認証、専門科目の推薦は今回の範囲に含めません。
    UIに合わせて判定を作るのではなく、この入力と出力を先に文書へ定義しました。
    ''', 'docs/requirements.md FR-001–010; docs/recommendation-search-api.md')
s.heading('最優先の「CSV送信 → 解析 → 表示」を土台に、履修検討までつなげる')
s.card(64,234,368,333,'01  成績CSV','修得状況を集計','入力：大学の成績CSV\n出力：合計・区分・科目一覧')
s.card(456,234,368,333,'02  入学年度別の規則','必要条件と照合','入力：集計結果＋規則\n出力：充足・不足・要確認')
s.card(848,234,368,333,'03  履修表＋公開カタログ','次の教養を探す','入力：年度・ターム・曜限\n　　　成績／履修表CSV\n出力：候補と不足への効果')
s.box(64,594,1152,60,'mint',10)
s.text(86,609,1108,33,'今回の対象外：成績予測・GPA分析・認証・専門科目の推薦',22,'green')

s = new('M・C・Vを分け、JSON APIでつなぐ', '03  全体設計｜責務の分離', 60, '''
    配布資料のM・C・Vに対応させると、モデルは正規化した成績や時間割、規則、開講カタログです。
    コントローラに相当するPython側では、CSVの読み取り、科目の分類、単位の配賦、要件判定、候補の照合を行います。
    ビューはファイル選択と結果表示に集中し、学務判定をもう一度計算しません。
    フロントとバックの間は、ファイルをmultipartで渡し、結果をバージョン付きJSONで返すAPIで分離しました。
    そのため、画面担当はバックエンド内部の関数やDOMに依存せず、APIの契約から作れます。
    学生データを保存するDBは導入せず、今回の利用中だけメモリで保持します。
    ''', 'docs/architecture.md §2–6; docs/data-contract.md')
s.heading('画面の作り替えと、学務規則の変更を切り離す')
for x, label, title, lines, fill in [(64,'V','ブラウザー','CSVの選択・送信\n単位・時間割・科目一覧\nメモリ上の表示状態','white'),(480,'C','Python / FastAPI','CSV解析 → 分類\n単位配賦・要件判定\n候補の時間・不足照合','mint'),(896,'M','データモデル','成績・履修表：メモリのみ\n規則：入学年度別JSON\n開講：開講年度別JSON','white')]:
    s.box(x,249,320,312,fill,line='line')
    s.text(x+23,272,260,46,label,34,'green',True)
    s.text(x+23,331,274,42,title,26,bold=True)
    s.text(x+23,405,274,126,lines,21,'muted')
s.text(403,365,65,55,'⇄',40,'green',True,align='center')
s.text(820,365,65,55,'⇄',40,'green',True,align='center')
s.text(64,597,1152,72,'ファイルは multipart/form-data で送信、判定結果はJSONで返却\nフロントエンドでは単位配賦・学務判定を再実装しない',24,'green',True)

s = new('学生データと、再利用する公開データを分ける', '04  データ設計｜モデル M', 55, '''
    データは二種類に分けました。左が学生ごとに変わる成績と履修表で、CSVから正規化してメモリだけで使います。
    成績は科目、単位、合否、区分など、履修表は開講番号と年度、ターム、曜日、時限を持ちます。
    右は再利用する公開データです。規則プロファイルは入学年度とプログラムで選び、専門科目の一覧もここへ置きます。
    一方、開講カタログは実際に授業が開かれる年度で管理します。入学年度と開講年度は別の軸です。
    現在のカタログは1科目6項目に絞りました。これにより、学生の成績を保存せずに公開データだけをGitで共有し、クローンから起動できます。
    ''', 'docs/architecture.md §4,6; docs/liberal-catalog.md §1; docs/handoff.md §2')
s.heading('入学年度の「規則」と、開講年度の「授業情報」は別の軸')
s.box(64,235,552,340,line='line')
s.box(640,235,576,340,'mint')
s.text(90,260,500,40,'利用中だけ保持する',27,bold=True)
s.text(90,327,500,145,'成績：科目・単位・合否・区分\n履修表：開講番号・年度・ターム・曜限\n学生情報・解析結果はメモリのみ',24,'muted')
s.text(90,516,500,33,'CSV原本・学生情報を保存しない',22,'green',True)
s.text(668,260,520,40,'公開情報として共有する',27,bold=True)
s.text(668,327,520,151,'規則：入学年度 × プログラム\n専門科目マスター：分類・必修確認\n開講カタログ：開講年度 × 科目',24,'muted')
s.text(668,516,520,33,'年度が変わっても既存規則を残す',22,'green',True)
s.box(64,598,1152,61,'white',10,line='line')
s.text(84,613,1112,34,'開講1科目＝開講番号／科目名／単位／区分／ターム／曜限',23,'green',True)

s = new('単位を「重複させず」、結論の不確かさも残す', '05  業務ロジック｜コントローラ C', 75, '''
    判定で最も注意したのは、取得済みの条件と、同じ単位の二重計上です。
    まず、合否が「合」で、単位数が有効な科目だけを取得済みにします。空欄や未知の結果を、勝手に合格や0単位へ変えません。
    次に対象プログラムの科目一覧と照合して分類し、必修、選択必修、選択へ規則に従って配賦します。
    例えば、この規則の自然系等の選択必修対象が13単位なら、10単位を選択必修に充て、残り3単位を選択へ回します。
    既に充てた10単位をもう一度選択へ加算しないことが重要です。
    最後に、各条件と個別必修の結果から総合判定を返します。全条件が確認できれば充足、確定した不足があれば不足、情報不足が結論へ影響する場合は要確認です。
    この画面の判定は参考情報で、大学の公式判定の代わりにはしません。公式規則と異なる独自の分類方針も明示しています。
    ''', 'docs/academic-rules.md; docs/rule-verification-2025-sis.md; docs/data-contract.md')
s.heading('CSVの値を検証 → 分類 → 配賦 → 条件別判定 → 総合判定')
s.box(64,230,1152,66,'green',10)
s.text(88,247,1104,36,'取得済み ＝ 合否が「合」 かつ 有効な単位数がある',27,'white',True)
for x, label, fill in [(64,'必修へ充当','white'),(448,'選択必修へ充当','mint'),(832,'残りを選択へ','white')]:
    s.box(x,325,352,75,fill,line='line')
    s.text(x+16,346,320,40,label,27,bold=True,align='center')
s.text(416,340,32,40,'→',27,'green',True,align='center')
s.text(800,340,32,40,'→',27,'green',True,align='center')
s.text(70,435,1140,72,'例：対象13単位 → 選択必修10単位 ＋ 選択3単位\n同じ10単位を、選択枠へもう一度加算しない',25,'green',True)
for x, label, sub, fill, color in [(64,'充足','全条件を確認できた','mint','green'),(456,'不足','確定した不足がある','white','red'),(848,'要確認','結論に必要な情報が不足','sand','amber')]:
    s.box(x,553,368,95,fill,line='line')
    s.text(x+20,566,325,35,label,25,color,True)
    s.text(x+20,611,325,27,sub,18,'muted')

s = new('現在地を先に、条件の内訳は必要なときに', '06  画面設計｜ビュー V：単位の状況', 60, '''
    こちらが現在動いている画面です。表示しているのは実在する学生ではなく、卒業条件を満たすよう作った架空の4年生です。
    修得済み124単位を、教養36単位、専門88単位として表示し、その下で卒業条件を確認できます。
    合計だけでなく、条件の内訳と個別必修16科目の確認結果を開けます。
    ただし初期状態では内訳を閉じ、必要な情報を選んで読めるようにしました。展開時に同じ条件が二重に表示される問題も修正済みです。
    また、CSVの学年に応じて、1年生には2年次進級、2・3年生には4年次進級と卒業、4年生には卒業を表示します。
    不足と要確認を色だけでなく文字でも区別し、細かな教養条件はどの学年でも確認できます。
    ''', 'static/prototype/; examples/README.md; docs/testing.md §23–24')
s.heading('実画面：架空の4年生・卒業確認用CSV（実在する学生情報は不使用）')
s.box(60,229,878,437,'white',12,line='line')
s.image('overview.png',72,238,854,415)
s.text(965,252,255,52,'124 単位',37,'green',True)
s.text(967,310,250,80,'教養36 ＋ 専門88\n個別必修16科目も確認',21,'muted')
s.text(967,420,250,44,'迷わない順序',25,bold=True)
s.text(967,478,250,142,'① 合計・内訳\n② 総合判定\n③ 開いて理由を確認',22,'muted')

s = new('「時間から探す」と「不足から探す」を分ける', '07  画面設計｜ビュー V：時間割・教養', 65, '''
    教養の探索は、二つの使い方を用意しました。時間割のマスを押す操作では、その時間にある教養科目を閲覧できます。
    この閲覧には成績CSVは必須ではありません。履修表があれば、候補の全ての曜日・時限について登録授業との重複を確認します。
    もう一つが、成績CSVと履修表CSVを使う不足単位の探索です。修得済みと同名の科目や時間が重なる候補を除き、
    残った候補を1科目ずつ仮に修得したとして、既存の判定器で不足への効果を比較します。
    教養条件を全て満たしていれば、専門だけが不足していても教養を薦めません。
    これはルールに基づく候補探索で、成績の予測や、最適な履修計画の自動作成ではありません。候補は学年で絞らず、履修許可は大学の情報で個別に確認します。
    ''', 'docs/recommendation-api.md; docs/recommendation-search-api.md; docs/testing.md §20,25')
s.heading('マスをクリックして候補を閲覧し、成績と照合して不足への効果を確認')
s.box(64,230,590,431,'white',12,line='line')
s.image('timetable.png',78,241,562,406)
s.text(690,238,520,40,'時間から：ターム・曜日・時限を選ぶ',25,'green',True)
s.text(690,299,520,38,'不足から：成績CSV ＋ 履修表CSVで照合',24,bold=True)
s.image('recommendation.png',692,354,265,228)
s.text(985,367,220,146,'修得済みを除外\n時間重複を除外\n1科目ずつ効果を比較',20,'muted')
s.box(691,594,525,65,'mint',10)
s.text(711,608,485,38,'教養が充足済みなら、教養を薦めない',22,'green',True)

s = new('正解を定義し、修正のたびに確かめる', '08  テスト｜正解動作と回帰確認', 60, '''
    テストでは、何が正しい動作かを架空CSVで先に定義しました。
    例えば、架空の1年生は34単位で2年次進級を満たすこと、架空の卒業用CSVは124単位で必修16科目も全て満たすことを確認します。
    境界値や、単位の余剰振替、二重計上、判定不能もテスト対象です。
    実装の見直しでは、教養の選択必修に使える区分の取りこぼしや、全条件を満たしたのに判定不能になる問題を修正し、再発しないようテストを追加しました。
    最新の確認記録ではPythonの364件と、従来画面42項目・試作画面33項目の計75項目が成功しています。
    さらにGitHubから新しくクローンした環境で、追加ZIPなしの起動も確認しました。ただし、ソフトウェアのテスト成功は、大学の公式判定による保証や使い勝手の評価とは別です。
    ''', 'docs/testing.md §20–25; tests/test_examples.py; tests/test_distribution.py')
s.heading('2026-10-28の検証記録。テストには架空データだけを使用')
for x, count, label, detail in [(64,'364','Python自動テスト','CSV解析・分類・配賦・API・配布'),(656,'75','ブラウザー確認項目','従来42 ＋ 試作33／表示・操作・連携')]:
    s.box(x,231,560,188,'green' if x==64 else 'white',line='line')
    s.text(x+26,252,200,87,count,68,'white' if x==64 else 'green',True)
    s.text(x+238,277,300,50,label,27,'white' if x==64 else 'ink',True)
    s.text(x+27,364,510,32,detail,20,'mint' if x==64 else 'muted')
for x, title, body in [(64,'34単位の架空1年生','第2年次進級：条件を満たす'),(456,'124単位の架空卒業例','卒業・必修16科目：条件を満たす'),(848,'不明値・境界値','未知を0や不合格へ変換しない')]:
    s.box(x,451,368,139,'white',line='line')
    s.text(x+22,473,324,40,title,23,bold=True)
    s.text(x+22,532,324,46,body,19,'muted')
s.text(67,622,1140,35,'バグの再現 → 公式資料・要件との照合 → 修正 → 回帰テスト',23,'green',True)

s = new('API契約を境に、分業へ移れる状態へ', '09  現在の進捗｜できたことと残る課題', 50, '''
    現在は、CSVからの集計、進級・卒業の参考判定、教養の候補閲覧と不足探索まで動いています。
    引き継ぎ文書とHTTP応答を使い、今回の作業ではバックエンドのソースを読まずに別の試作フロントを作成できました。
    ただし過去開発の知識はあるため、前知識のない第三者による完全な独立検証とまでは言えません。
    フロント担当は画面と状態管理を、バック担当はAPIと判定を担当する境界を文書化しています。
    開発にはAIエージェントも使用していますが、学務判定自体は公式資料と明示した前提に基づくルール処理です。
    次に必要なのは、利用者にとっての分かりやすさの確認と、応答スキーマの機械可読化、拡張前の規則検証の整理です。
    ''', 'docs/handoff.md; docs/prototype-handoff-test.md; docs/backlog.md')
s.heading('現在の試作は、引き継ぎ文書とHTTP応答を使って接続・表示を確認した')
s.box(64,238,552,351,'mint')
s.text(89,263,500,42,'実装・確認済み',29,'green',True)
s.text(89,334,500,206,'CSV解析・進級／卒業の参考判定\n時間割からの教養閲覧・不足探索\n分離した試作フロントエンド\nGit clone ＋ Dockerで初回起動',24,'ink')
s.box(640,238,576,351,'white',line='line')
s.text(665,263,520,42,'次に取り組む',29,bold=True)
s.text(665,334,520,206,'実際の利用者からのフィードバック\nAPI応答スキーマ・型の整備\n別年度・プログラム追加時の規則検証\n認証・分析・予測は必要に応じて検討',24,'muted')
s.text(66,619,1150,37,'担当境界：フロント＝操作・表示・メモリ管理／バック＝CSV検証・判定・探索',22,'green',True)

s = new('次は、学生が迷わず使えるかを確かめる', '10  これからの計画と、いただきたい意見', 40, '''
    MVPの機能を、データ設計から実画面・テストまでつなげられました。
    次は、学生が判定理由を理解し、自然に候補を探せるかを確かめます。
    計画案は、11月4日に意見反映、11日に連携確認、18日にリハーサル、25日に最終発表です。
    不足と要確認の違い、二つの探索操作について、ご意見をいただきたいです。
    ありがとうございました。質疑後の5分で、指摘と対応の優先度を整理します。
    ''', '授業配布資料 p.1,4; docs/roadmap.md; docs/backlog.md')
s.heading('計画案：中間発表の意見を反映し、11/25の最終発表へ')
for x, date, label in [(64,'11/4','意見を反映'),(360,'11/11','分業後の連携確認'),(656,'11/18','発表リハーサル'),(952,'11/25','最終発表')]:
    s.box(x,242,264,138,'white',line='line')
    s.text(x+20,259,224,52,date,35,'green',True)
    s.text(x+20,327,224,36,label,21,'muted')
s.box(64,420,1152,189,'green')
s.text(90,443,1090,40,'フィードバックをいただきたいこと',28,'white',True)
s.text(90,507,1090,84,'① 不足と「要確認」の違いは伝わるか？\n② 時間から探す／不足から探す操作は分かりやすいか？',27,'white')
s.text(68,633,1140,30,'質疑 5分 → 指摘を整理し、対応の優先度を決める 5分',21,'muted')

s = new('APIは機能ごとに独立して呼び出せる', '補足 A  分業時のAPI一覧', 0, '''
    APIは事前に別の解析APIを呼んだことを要求せず、各リクエストで元CSVを検証します。
    共通のprofile_idを送り、学年は候補の絞り込みに使いません。学生情報のセッションIDや保存先は作っていません。
    CSV上限は1ファイル5 MiB、探索は成績と履修表の2ファイルです。エラーは機械可読コードと日本語メッセージで返します。
    応答JSONの厳密な機械可読スキーマ・型整備は、今後の課題です。
    ''', 'docs/handoff.md §4; docs/data-contract.md; docs/recommendation-api.md; docs/recommendation-search-api.md', True)
s.heading('CSVをmultipartで送り、判定・候補はJSONで受け取る')
rows=[('GET /api/v1/rule-profiles','対象カリキュラムと規則の公開情報'),('POST /api/v1/reports','成績CSV → 集計・学年別要件・判定'),('POST /api/v1/timetables','履修表CSV → 年度・ターム・占有曜限'),('GET /api/v1/recommendation-catalogs','候補を検索できる年度・プロファイル'),('POST /api/v1/recommendations','時限指定 → その時間の教養候補'),('POST /api/v1/recommendation-searches','成績＋履修表 → 不足を補う教養候補')]
for index,(path,meaning) in enumerate(rows):
    y=235+index*56
    s.box(64,y,1152,52,'white' if index%2==0 else 'mint',5)
    s.text(80,y+13,650,30,path,19,'green',True)
    s.text(754,y+13,440,30,meaning,18,'muted')
s.text(66,607,1150,63,'元CSVは各APIが再検証／レポートID・Cookie不要／学生データはメモリのみ\nAPI形式の詳細は引き継ぎ文書を正本とする',21,'green')

s = new('対象範囲と、まだ保証できないこと', '補足 B  質疑用：判定・推薦の制約', 0, '''
    学務判定は2025年度入学・知能情報の規則だけに対応し、同じ規則で1〜4年生の表示を切り替えます。
    留年・編入がなく、学年と在学期間が一致する前提です。留学生向け代替、早期卒業、他大学単位認定は対象外です。
    対象プログラムの一覧にない専門科目を教養選択へ回すのは、利用者が選んだ独自方針であり、大学公式の読替えではありません。
    教養カタログは2026年度の代表63開講です。月〜金・1〜5限の100枠のうち85枠に候補があり、全開講を網羅していません。
    候補は学年では絞り込まず、複雑な聴講指定・時限未定・集中講義等を採用しません。ターム0除外は利用者指定です。
    履修許可、先修条件、抽選、複数候補の同時履修、将来の成績は保証しません。不明な必要性は確定推薦と分けます。
    ''', 'docs/rule-verification-2025-sis.md §13; docs/liberal-catalog.md; docs/recommendation-search-api.md', True)
s.heading('学務判定は参考情報。未知の条件を推測して「充足」にしない')
s.box(64,237,552,399,'white',line='line')
s.text(88,261,504,44,'学務判定',28,'green',True)
s.text(88,332,504,210,'2025年度入学・知能情報の規則\n留年・編入なしを前提\n留学生代替・早期卒業等は対象外\n他プログラム専門→教養選択は\n利用者指定の独自方針',23,'muted')
s.box(640,237,576,399,'white',line='line')
s.text(665,261,526,44,'教養の候補探索',28,'green',True)
s.text(665,332,526,258,'2026年度・代表63開講／85/100枠\n集中・時限未定等は対象外\n学年では候補を変更しない\n履修許可・先修条件は未確認\n順位付け・履修計画最適化は未実装',23,'muted')

s = new('根拠と、同じ状態を確認する方法', '補足 C  参考資料・動作確認', 0, '''
    発表構成は授業配布資料の3ページと5ページの骨子、発表時間は4ページに合わせました。
    実装の根拠はリポジトリ内の要件、学務規則、API契約、テスト記録で確認できます。
    学務規則の正本となる公式資料はdocs/academic-rules.mdに整理しています。
    クローン後、credit-dashboardディレクトリでdocker compose up --buildを実行し、localhostのprototypeを開きます。
    サンプルCSVは全て架空です。実在する学生データを発表、ログ、Git、外部サービスへ送らないでください。
    質疑でその場の画面動作が難しい場合にも、スライド内の画像とサンプルの期待値で説明できます。
    ''', '授業配布資料 p.3–5; docs/handoff.md; docs/testing.md §25', True)
s.heading('発表内容は2026-10-28時点。画面例はすべて架空データ')
s.box(64,235,696,410,'white',line='line')
s.text(87,256,650,40,'確認した資料',27,bold=True)
s.text(87,318,650,270,'授業配布資料：中間発表 PM（p.3–5）\n要件：docs/requirements.md\n設計：docs/architecture.md\n学務根拠：docs/academic-rules.md\nAPI：docs/data-contract.md ほか\n検証：docs/testing.md §25',22,'muted')
s.box(784,235,432,410,'green')
s.text(808,259,384,40,'クローン後に起動',27,'white',True)
s.text(808,331,384,102,'docker compose up --build',24,'white',True)
s.text(808,468,384,110,'localhost:8000/prototype/\n架空CSV3点をGitに同梱\n追加の手渡しZIPは不要',21,'white')


def footer(slide, index):
    if index == 0:
        return
    label = f'{index+1:02d} / 11' if not slide.appendix else 'APPENDIX ' + chr(65 + index - 11)
    slide.box(64,678,1152,1,'line',0)
    slide.text(65,688,1000,23,'単位ノート  |  中間発表 2026.10.28',14,'muted')
    slide.text(1070,688,145,23,label,14,'muted',align='right')


def render():
    assert len(slides) == 14
    assert sum(slide.seconds for slide in slides) == 600
    presentation = Presentation()
    presentation.slide_width = Inches(W/96)
    presentation.slide_height = Inches(H/96)
    presentation.core_properties.title = '単位ノート｜情報システム基礎実習 中間発表'
    presentation.core_properties.subject = 'MVP要件・データ設計・業務ロジック・UI/UX・検証'
    presentation.core_properties.author = '単位ノート'
    presentation.core_properties.last_modified_by = ''
    pdf = canvas.Canvas(str(ROOT/'midterm-2026-10-28.pdf'), pagesize=(W*.75,H*.75))
    pdf.setTitle(presentation.core_properties.title)
    pdf.setAuthor('単位ノート')
    pdf.setSubject('2026-10-28時点のプロジェクト中間発表。実画面は架空データのみ。')
    for index, slide in enumerate(slides):
        footer(slide,index)
        target = presentation.slides.add_slide(presentation.slide_layouts[6])
        target.background.fill.solid();target.background.fill.fore_color.rgb=RGBColor.from_string(COLORS['bg'])
        target.notes_slide.notes_text_frame.text = '\n'.join([
            f'{index+1}. {slide.title}',
            f'目安：{slide.seconds}秒' if slide.seconds else '質疑用の補足（本編10分には含めない）',
            slide.note,
            '根拠：'+slide.source,
        ])
        pdf.saveState();pdf.scale(.75,.75)
        pdf.setFillColorRGB(*[int(COLORS['bg'][i:i+2],16)/255 for i in (0,2,4)])
        pdf.rect(0,0,W,H,fill=1,stroke=0)
        for item_index, item in enumerate(slide.items):
            x,y,w,h=[item[key] for key in ['x','y','w','h']]
            if min(x,y)<-0.01 or x+w>W+.01 or y+h>H+.01:
                raise ValueError(f'Element outside slide {index+1}: {item_index}')
            if item['kind']=='box':
                shape=target.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if item['radius'] else MSO_SHAPE.RECTANGLE, Inches(x/96),Inches(y/96),Inches(w/96),Inches(h/96))
                shape.fill.solid();shape.fill.fore_color.rgb=RGBColor.from_string(item['fill'])
                if item['radius']:
                    shape.adjustments[0]=min(.16,item['radius']/min(w,h))
                if item['line']:
                    shape.line.color.rgb=RGBColor.from_string(item['line']);shape.line.width=Pt(.75)
                else:
                    shape.line.fill.background()
                pdf.setFillColorRGB(*[int(item['fill'][i:i+2],16)/255 for i in (0,2,4)])
                if item['line']:
                    pdf.setStrokeColorRGB(*[int(item['line'][i:i+2],16)/255 for i in (0,2,4)]);pdf.setLineWidth(1)
                pdf.roundRect(x,H-y-h,w,h,item['radius'],fill=1,stroke=int(bool(item['line'])))
            elif item['kind']=='image':
                image=ROOT/item['file']
                target.shapes.add_picture(str(image),Inches(x/96),Inches(y/96),Inches(w/96),Inches(h/96))
                pdf.drawImage(ImageReader(str(image)),x,H-y-h,width=w,height=h,mask='auto')
            else:
                shape=target.shapes.add_textbox(Inches(x/96),Inches(y/96),Inches(w/96),Inches(h/96))
                frame=shape.text_frame;frame.clear();frame.word_wrap=False
                frame.margin_left=frame.margin_right=frame.margin_top=frame.margin_bottom=0
                from pptx.enum.text import PP_ALIGN
                alignment={'left':PP_ALIGN.LEFT,'center':PP_ALIGN.CENTER,'right':PP_ALIGN.RIGHT}[item['align']]
                for line_index, line in enumerate(item['text'].split('\n')):
                    para=frame.paragraphs[0] if line_index==0 else frame.add_paragraph()
                    para.text=line;para.alignment=alignment
                    para.space_before=para.space_after=Pt(0)
                    para.line_spacing=Pt(item['leading']*.75)
                    para.font.name='Meiryo';para.font.size=Pt(item['size']*.75)
                    para.font.bold=item['bold'];para.font.color.rgb=RGBColor.from_string(item['color'])
                    # 日本語にも同じ書体を指定し、Officeの既定フォントへの切替を避ける。
                    from pptx.oxml.xmlchemy import OxmlElement
                    properties=para._p.get_or_add_pPr().get_or_add_defRPr()
                    east_asian=OxmlElement('a:ea');east_asian.set('typeface','Meiryo');properties.append(east_asian)
                font='MeiryoBold' if item['bold'] else 'Meiryo'
                pdf.setFont(font,item['size'])
                pdf.setFillColorRGB(*[int(item['color'][i:i+2],16)/255 for i in (0,2,4)])
                baseline=H-y-pdfmetrics.getAscent(font)*item['size']/1000
                for line_index,line in enumerate(item['text'].split('\n')):
                    dx=x
                    width=pdfmetrics.stringWidth(line,font,item['size'])
                    if width>w+2:raise ValueError(f'Line too wide on slide {index+1}')
                    if item['align']=='center':dx+=(w-width)/2
                    if item['align']=='right':dx+=w-width
                    pdf.drawString(dx,baseline-line_index*item['leading'],line)
            target.shapes[-1].name=f'slide-{index+1}-element-{item_index+1}'
        pdf.restoreState();pdf.showPage()
    pdf.save()
    presentation.save(ROOT/'midterm-2026-10-28.pptx')
    elapsed=0
    notes=['# 中間発表の発表原稿','', '本編11枚・目安10分。補足3枚は質疑用。班名・発表者名は記載しない。', '']
    for index,slide in enumerate(slides):
        notes.extend([f'## {index+1}. {slide.title}', ''])
        if slide.seconds:
            start=elapsed;elapsed+=slide.seconds
            notes.extend([f'時間：{start//60}:{start%60:02d}〜{elapsed//60}:{elapsed%60:02d}（{slide.seconds}秒）',''])
        else:notes.extend(['質疑用の補足。本編の時間には含めない。',''])
        notes.extend([slide.note,'','根拠：'+slide.source,''])
    (ROOT/'speaker-notes.md').write_text('\n'.join(notes),encoding='utf-8')
    manifest=[dict(number=i+1,title=s.title,section=s.section,seconds=s.seconds,appendix=s.appendix,source=s.source,
                   note=s.note,items=s.items) for i,s in enumerate(slides)]
    (ROOT/'slide-content.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    previews=ROOT/'previews';previews.mkdir(exist_ok=True)
    with pypdfium2.PdfDocument(str(ROOT/'midterm-2026-10-28.pdf')) as document:
        for index,page in enumerate(document):
            image=page.render(scale=4/3).to_pil()
            image.save(previews/f'slide-{index+1:02}.png')
    montage=Image.new('RGB',(1280,5*265+16),'#E8EEEB')
    draw=ImageDraw.Draw(montage)
    for index in range(14):
        with Image.open(previews/f'slide-{index+1:02}.png') as image:
            image.thumbnail((400,225))
            x=16+(index%3)*421;y=16+(index//3)*265
            montage.paste(image,(x,y));draw.text((x+6,y+231),f'{index+1:02d}',fill='#20382F')
    montage.save(ROOT/'overview.png')
    print(json.dumps(dict(slides=14,main_slides=11,appendix=3,main_seconds=elapsed,pptx_bytes=(ROOT/'midterm-2026-10-28.pptx').stat().st_size,pdf_bytes=(ROOT/'midterm-2026-10-28.pdf').stat().st_size)))


if __name__=='__main__':
    render()
