# サーバー側・関数の入力と戻り値一覧

作成日：2026-11-11。対象コミット：`38a1734`。先に[コードの読み方レポート](backend-code-reading-report.md)を読むと、この一覧を引きやすい。

表の戻り値は、`async def`では`await`した後の値を表す。非同期関数を呼ぶだけでは、通常の辞書ではなくコルーチンが返る。`None`でも、リストへの追加・保持データの削除・HTTP送信などの作用を持つ関数がある。

`Class.__init__`自体の戻り値は`None`だが、`Class(...)`という生成式全体では新しいインスタンスを得る。`self`はそのインスタンス、`cls`はクラス自身で、通常の呼出しでは自分で渡さない。名前に複数の点があるものは、クラスのメソッドまたは関数の内部で定義された関数を表す。

`scope`はASGIの要求情報、`receive`は受信するための非同期関数、`send`は応答メッセージを送るための非同期関数。これらは通常Uvicornとフレームワークが用意するため、まずはCSV・判定の関数を読むとよい。

入力にある`report`は分類済み成績、`profile`は年度・プログラムの規則、`timetable`は履修表解析結果、`catalog`は開講候補JSON、`context`は対象プロファイル・年度・ターム・必要なら曜限である。

## 1. 関数・メソッド

### server.py

HTTP受付と応答の組立て。内部コールバックも含める。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`ApiError.__init__`](../server.py#L51) | HTTP番号・機械可読コード・日本語メッセージ・任意の詳細 | None。例外オブジェクトに情報を設定 | API処理を中断して登録ハンドラーへ伝えるための例外を準備する。 |
| [`_error_payload`](../server.py#L88) | code、message、任意のdetails | errorを最上位キーに持つdict | detailsが空ならキーを省略する。 |
| [`SecurityHeadersMiddleware.__init__`](../server.py#L98) | 次に呼ぶASGIアプリapp | None。self.appを設定 | ミドルウェアが包むアプリを保持する。 |
| [`SecurityHeadersMiddleware.__call__`](../server.py#L101) | scope・receive・send | None。HTTP応答を送る | 非HTTPは通過。HTTPへ保護ヘッダーを加え、応答開始前の予期しない例外を500へ変える。 |
| [`SecurityHeadersMiddleware.__call__.send_with_headers`](../server.py#L108) | ASGI応答メッセージmessage | None。変更したメッセージをsendへ渡す | 応答開始時にno-store・CSP等を設定する内部関数。 |
| [`_read_report_upload`](../server.py#L140) | Request、必須ファイルの指定、許可する文字列フィールド | ReportUpload(raw: bytes, fields: dict) | 汎用受信からfile一つを取り出す。任意ファイルがない場合のrawは空bytes。 |
| [`_read_upload`](../server.py#L148) | Request、ファイル欄名・必須欄名・許可する文字列欄名の集合 | MultipartUpload(files: dict, fields: dict) | サイズ上限を確認してメモリへ受信する。未知の欄は採用せず、既知欄の重複等は例外。 |
| [`_read_upload.on_part_begin`](../server.py#L164) | 引数なし。外側のcurrentを利用 | None。新しいMultipartPartへ置換 | multipartの一部分が始まる際の作業領域を作る。 |
| [`_read_upload.on_header_field`](../server.py#L168) | data: bytes、start・end | None。header_nameへ追加 | 分割受信したヘッダー名の断片を結合する。 |
| [`_read_upload.on_header_value`](../server.py#L171) | data: bytes、start・end | None。header_valueへ追加 | 分割受信したヘッダー値の断片を結合する。 |
| [`_read_upload.on_header_end`](../server.py#L174) | 引数なし | None。headersへ格納して作業バッファを空にする | 一組のヘッダーを確定する。 |
| [`_read_upload.on_headers_finished`](../server.py#L179) | 引数なし | None。field_name・has_filename・captureを設定 | どの入力欄か、ファイル部分か、採用する入力かを判断する。ファイル名そのものは結果に保持しない。 |
| [`_read_upload.on_part_data`](../server.py#L195) | data: bytes、start・end | None。current.dataへ追加 | 採用対象だけを受け取り、ファイル5 MiB・文字列256バイトを確認する。 |
| [`_read_upload.on_part_end`](../server.py#L206) | 引数なし | None。uploadedまたはform_fieldsを更新 | 一部分を確定し、重複・空ファイル・文字コードを検証する。 |
| [`_residence_years`](../server.py#L268) | フォーム由来の文字列またはNone | int、float、None | 空欄はNone。0〜100の有限数を取得し、それ以外はApiError。 |
| [`_selected_profile`](../server.py#L288) | profile_id文字列またはNone | 規則プロファイルのdict | 空なら既定、指定ありなら検証済みIDを解決。未対応IDは422。 |
| [`_append_scope_warning`](../server.py#L302) | reportとprofile | None。report.warningsへ必要時に追記 | CSV所属から選択プログラムとの対応を確認できるか調べる。プロファイルを自動変更しない。 |
| [`lifespan`](../server.py#L316) | FastAPIアプリ | async context manager。yieldする値はNone | 起動時に掃除タスクを作り、終了時にタスク停止とストア全消去を行う。 |
| [`api_error_handler`](../server.py#L347) | RequestとApiError | JSONResponse | 例外のHTTP番号・コード・メッセージ・詳細を共通形式で返す。 |
| [`recommendation_error_handler`](../server.py#L355) | RequestとRecommendationError | JSONResponse | 公開カタログ・推薦処理の例外をHTTPエラーへ変換する。 |
| [`session_error_handler`](../server.py#L360) | RequestとSessionError | JSONResponse | Cookie・CSRF・期限・競合・容量の例外をHTTPエラーへ変換する。 |
| [`validation_error_handler`](../server.py#L365) | RequestとRequestValidationError | 422のJSONResponse | 受信内容の検証失敗を、元入力を転記しない共通メッセージで返す。 |
| [`http_error_handler`](../server.py#L373) | RequestとHTTPException | JSONResponse | 404・405等を機械可読なエラーへ統一する。 |
| [`healthz`](../server.py#L386) | 引数なし | statusがokのdict | サーバーの稼働確認。学生やセッションを返さない。 |
| [`rule_profiles`](../server.py#L391) | 引数なし | profilesとdefault_profile_idを持つdict | 対応する規則と実装済み要件を、選択肢用の公開情報へ変換する。 |
| [`legacy_report`](../server.py#L410) | 引数なし | 410のJSONResponse | 廃止済み固定CSVの入口。プロジェクト内CSVを読まない。 |
| [`create_report`](../server.py#L421) | 成績CSVのmultipartを含むRequest | ReportResponse相当のdict | ファイル受信、規則選択、解析、在学期間決定、学年別要件評価を組み立てる。 |
| [`create_timetable`](../server.py#L459) | 履修表CSVのmultipartを含むRequest | TimetableResponse相当のdict | 受信して時間割パーサーへ渡し、解析エラーをHTTPエラーへ変える。 |
| [`_recommendation_catalogs`](../server.py#L468) | 引数なし。環境変数を参照 | 公開カタログのlist[dict] | RECOMMENDATION_CATALOG_DIRまたは既定フォルダーから読込み・検証する。 |
| [`recommendation_catalogs`](../server.py#L474) | 引数なし | schema_versionとcatalogsを持つdict | 検索可能な年度・プロファイル・タームなどを返す。 |
| [`create_recommendations`](../server.py#L479) | 年度・ターム・曜日・時限、任意の履修表CSVを含むRequest | SlotRecommendationsResponse相当のdict | 入力範囲と対象カタログを確認し、指定曜限の検索を呼ぶ。 |
| [`create_recommendation_search`](../server.py#L502) | 年度・ターム、成績CSVと履修表CSVを含むRequest | RecommendationSearchResponse相当のdict | 両CSVを解析し、不足効果の探索へ渡す。前処理として成績APIを呼ぶ必要はない。 |
| [`_upload_workspace`](../server.py#L527) | Request、kindがreportまたはtimetable | SessionWorkspaceResponse相当のdict | 更新開始→既存の成績または履修表API関数を再利用→保持確定の順に進む。 |
| [`upload_session_report`](../server.py#L538) | Request | 成績を保持したworkspaceのdict | _upload_workspaceをkind=reportで呼ぶHTTP入口。 |
| [`upload_session_timetable`](../server.py#L543) | Request | 履修表を保持したworkspaceのdict | _upload_workspaceをkind=timetableで呼ぶHTTP入口。 |
| [`_clear_workspace`](../server.py#L547) | Request、kind | 削除後のworkspaceのdict | CSRF・更新番号を確認し、同種結果だけ消して更新番号を進める。 |
| [`clear_session_report`](../server.py#L556) | Request | 成績がNoneのworkspaceのdict | 個別成績クリアの入口。履修表は保持する。 |
| [`clear_session_timetable`](../server.py#L561) | Request | 履修表がNoneのworkspaceのdict | 個別履修表クリアの入口。成績は保持する。 |
| [`_workspace_recommendation_inputs`](../server.py#L565) | Request、slotがTrueなら曜日・時限も要求 | credentials、snapshot、profile、context、catalogのタプル | 保持結果と検索条件の整合性を確認する。保持成績と異なる対象は409。 |
| [`session_recommendations`](../server.py#L591) | 条件だけのmultipartを含むRequest | SlotRecommendationsResponse相当のdict | 保持履修表で曜限検索し、処理後も同じ更新番号・期限か確認する。 |
| [`session_recommendation_search`](../server.py#L599) | 条件だけのmultipartを含むRequest | RecommendationSearchResponse相当のdict | 保持成績・履修表の両方を必須とし、探索後に更新番号・期限を再確認する。 |
| [`unknown_api_route`](../server.py#L615) | Requestとapi_path | 正常な戻り値なし。必ずApiError | 既知URLのメソッド違いなら405、未知URLなら404を返す。 |

### parser.py

成績CSVの解析。ここだけでは進級・卒業判定を完成させない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`CsvFormatError.__init__`](../parser.py#L29) | 安全な説明文、任意のコード・詳細 | None。例外の属性を設定 | CSVの形式・値を解釈できない理由を上位処理へ渡す。 |
| [`_number`](../parser.py#L41) | 単位数の文字列と行番号 | DecimalまたはNone | 空欄と数値を区別する。不正値・負数・無限大は例外。 |
| [`_json_number`](../parser.py#L59) | DecimalまたはNone | int、float、None | 内部の正確な計算値をJSONへ返せる型へ変換する。 |
| [`_student_info`](../parser.py#L65) | 科目見出しより前のlist[list[str]] | name・student_number・affiliation・gradeのdict | 固定位置ではなくラベルの次のセルから値を取る。見つからない値やプレースホルダーはNone。 |
| [`parse_csv_bytes`](../parser.py#L78) | CSVのbytes、任意のprofile | schema 2の成績dict | 見出しを検出して全科目を検証・分類・集計する。evaluationsは空リストで返す。 |
| [`parse_csv_bytes.public_bucket`](../parser.py#L227) | Decimalを含む集計用dict | 数値がint・floatへ変わったdict | 集計結果をJSON向けへ整える内部関数。 |
| [`parse_csv`](../parser.py#L257) | ファイルパス、任意のprofile | parse_csv_bytesと同じ成績dict | ローカル互換入口。アップロードAPIはこの関数を呼ばない。 |

### classification.py

科目を計算用の分類へ変換。単位数・合否・総合判定はここで決めない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`curriculum_profile`](../classification.py#L15) | 任意のprofile | institution・faculty・program・admission_year・rules_version・policy_notesのdict | APIに表示する規則の対象情報を作る。 |
| [`normalize_course_name`](../classification.py#L36) | 科目名、任意のprofile | 照合用のstr | 設定された接尾辞を繰り返し外し、明示された別名を正式名へ置換する。 |
| [`classify_category`](../classification.py#L56) | CSV科目区分、任意のprofile | major、field、detail、curriculum_area、classification_statusのタプル | 接頭辞と括弧の中身から教養・専門・不明と区分を取得する。 |
| [`classify_specialized`](../classification.py#L82) | CSV科目区分、必選区分、任意のprofile | course_groupとrequirement_codeのタプル | 専門系なら基礎・応用の群とA〜Eを取る。該当しなければNone。 |
| [`course_catalog_index`](../classification.py#L104) | 任意のprofile | 名称キーから科目マスター項目を引くdict、またはNone | 一回の解析に使う名前・別名の索引。単位数をCSVへ上書きしない。 |
| [`classify_course`](../classification.py#L116) | 科目名・CSV区分・必選区分、profileと索引 | 分類値と分類理由を持つdict | 既知の対象外と専門マスターを照合し、一覧外専門のMVP方針を適用する。 |

### academic_rules.py

公開JSONの読込みと構造・参照の検証。実行時はPythonコードで検証する。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_require_mapping`](../academic_rules.py#L51) | valueとエラー位置path | 検証済みdict | 辞書でなければRuleDataError。 |
| [`_require_list`](../academic_rules.py#L57) | valueとpath | 検証済みlist | リストでなければRuleDataError。 |
| [`_require_string`](../academic_rules.py#L63) | valueとpath | 空でないstr | 文字列の存在と空欄でないことを確認する。 |
| [`_require_nonnegative_number`](../academic_rules.py#L69) | valueとpath | 0以上のintまたはfloat | 真偽値・数値でない値・負数を拒否する構造検証用ヘルパー。 |
| [`_unique_ids`](../academic_rules.py#L75) | ID付きオブジェクトのlistとpath | IDのset[str] | IDを取り出し、重複がないか確認する。 |
| [`_require_string_list`](../academic_rules.py#L86) | valueとpath | 検証済みlist[str] | リストの各要素を空でない文字列として確認する。 |
| [`_validate_source_refs`](../academic_rules.py#L93) | 参照のlist、path、有効な資料ID集合 | None | 資料IDと冊子・PDFページ番号の構造を確認し、不正なら例外。 |
| [`_validate_selector`](../academic_rules.py#L112) | 科目選択条件のdictとpath | None | 部分一致名称やany_ofなどの最低限の構造を再帰確認する。任意キーすべてを検証する汎用スキーマ実行器ではない。 |
| [`validate_rule_profile`](../academic_rules.py#L134) | 読込み直後のprofile | 検証した同じdict | 対象、分類、要件、依存ID、根拠、配賦設定等の整合性を確認する。 |
| [`load_rule_profile`](../academic_rules.py#L378) | 任意のJSONパス。省略時は既定2025年度規則 | 検証済みprofileのdict | UTF-8 JSONを読んでvalidate_rule_profileへ渡す。 |
| [`catalog_name_key`](../academic_rules.py#L389) | 科目名str | NFKC正規化して空白を除いたstr | 全半角・ローマ数字・空白の違いを照合時に吸収する。類似名の推測はしない。 |
| [`validate_course_catalog`](../academic_rules.py#L394) | 専門科目マスターのdict、対応profile | 検証した同じdict | 対象ID、名称・別名、群、A〜E、必修指定、資料参照を確認する。 |
| [`load_course_catalog`](../academic_rules.py#L468) | 科目マスターのパス、任意のprofile | 検証済み科目マスターのdict | JSONを読み、validate_course_catalogへ渡す。 |
| [`load_profile_course_catalog`](../academic_rules.py#L481) | profile | 科目マスターdictまたはNone | 設定された相対パスをrules内に限定して読む。指定なしならNone。 |
| [`discover_rule_profiles`](../academic_rules.py#L492) | 任意のrulesルート | 検証済みprofileのlist[dict] | profile.jsonを列挙し、プロファイルIDの重複も検証する。 |
| [`load_rule_profile_by_id`](../academic_rules.py#L501) | profile_id、任意のrulesルート | 一致する検証済みprofileのdict | 列挙済みIDから選ぶ。未対応ならRuleProfileNotFoundError。 |
| [`public_rule_profile`](../academic_rules.py#L517) | profile | 画面用の公開メタデータdict | 対象名・年度・注意書き・要件一覧だけを取り出す。 |

### requirement_evaluator.py

分類済みのcoursesと規則を比較する。HTTPやCookieを扱わない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_decimal`](../requirement_evaluator.py#L22) | 単位数・年数等の値 | Decimal | 有限の非負数へ変換する。Noneの内部変換値は0だが、呼出し側で未確定かを別管理する。 |
| [`_json_number`](../requirement_evaluator.py#L36) | Decimal | intまたはfloat | 計算結果をJSON向けへ変換する。 |
| [`_result_from_lower_bound`](../requirement_evaluator.py#L40) | 確認済み値earned、最低値minimum、不確定候補の有無 | statusとreason_codeのタプル | 確認済みで充足→不明の影響→確定不足の順で三値を決める。 |
| [`_selector_match`](../requirement_evaluator.py#L52) | 一科目course、選択条件selector | include・exclude・uncertainのいずれか | 区分・群・名称・A〜E等を比較し、any_ofも評価する。 |
| [`_evaluate_credit_condition`](../requirement_evaluator.py#L136) | 最低単位条件、courses | 条件結果dict | 対象の修得済みを合計し、コード別上限を適用。重複・未確定は別に記録する。 |
| [`_evaluate_named_course_condition`](../requirement_evaluator.py#L191) | 指定科目群の最低単位条件、courses | matched_course_names等を含む条件結果dict | 指定した名称の確認済み単位を合計する。 |
| [`_evaluate_shared_surplus_condition`](../requirement_evaluator.py#L231) | 超過条件、先に評価した結果のID索引 | source_surplus_credits等を含む条件結果dict | 参照条件ごとの最低値を超えた分だけを合計する。 |
| [`_evaluate_required_courses_condition`](../requirement_evaluator.py#L271) | 個別必修条件、courses、requirement_id、profile | 一科目ずつのcourse_resultsと全体結果のdict | マスターのrequired_forを基準に修得を確認。単位の再加算はしない。 |
| [`_evaluate_residual_credit_condition`](../requirement_evaluator.py#L356) | 残余条件、courses、先に評価した結果のID索引 | 充当内訳・残余単位を含む条件結果dict | 対象合計から各先行枠のmin(確認済み, 最低値)を差し引く。 |
| [`_evaluate_residence_condition`](../requirement_evaluator.py#L399) | 在学期間条件、年数またはNone、値の出所 | minimum_years・confirmed_years等を持つ条件結果dict | 未入力ならunknown、入力ありなら最低年数と比較する。 |
| [`_overall_status`](../requirement_evaluator.py#L429) | statusを持つ条件結果のlist | satisfied・not_satisfied・unknown | 確定不足が優先。なければ不明、全条件充足ならsatisfied。 |
| [`_condition_description`](../requirement_evaluator.py#L440) | 一条件の評価結果dict | 日本語説明str | 値・理由・条件の種類から、フロントが再判定せず表示できる文を作る。 |
| [`_source_details`](../requirement_evaluator.py#L497) | profileとsource_refs | 資料名・URL・冊子／PDFページのlist[dict] | 資料IDを実際の公開資料情報へ展開する。ダウンロードはしない。 |
| [`_caveat_details`](../requirement_evaluator.py#L516) | profileと要確認IDのlist | 要確認内容のlist[dict] | IDに対応する質問文・状態を取り出す。 |
| [`_overall_description`](../requirement_evaluator.py#L531) | 総合status | 日本語説明str | 三値に対応する総合説明を選ぶ。 |
| [`student_grade_year`](../requirement_evaluator.py#L539) | report | 1以上のintまたはNone | 学年の文字列を整数化。解釈できない文字列はNone。 |
| [`requirement_ids_for_grade`](../requirement_evaluator.py#L548) | 整数学年またはNone | 表示する要件IDのtuple[str, ...] | 1年は第2年次＋卒業、2・3年は第4年次＋卒業、4年以上は卒業、不明は全対象。 |
| [`_evaluate_requirement`](../requirement_evaluator.py#L559) | requirement_id、report、在学年数と出所、profile | 一つの要件のEvaluation相当dict | kind別に条件関数を呼び、説明・根拠・総合判定を付ける。 |
| [`evaluate_second_year_progression`](../requirement_evaluator.py#L647) | report、任意の在学年数・出所・profile | 第2年次進級の評価dict | 共通評価器へprogression_year_2を渡す。 |
| [`evaluate_fourth_year_progression`](../requirement_evaluator.py#L667) | report、任意の在学年数・出所・profile | 第4年次進級の評価dict | 共通評価器へprogression_year_4を渡す。 |
| [`evaluate_graduation`](../requirement_evaluator.py#L686) | report、任意の在学年数・出所・profile | 卒業の評価dict | 共通評価器へgraduationを渡す。出所等の省略時は在学期間を学年から自動補完しない。 |
| [`evaluate_supported_requirements`](../requirement_evaluator.py#L705) | report、任意の在学年数・出所・profile | 学年別要件評価のlist[dict] | 対応する要件を選び、各評価関数を呼ぶ。 |

### timetable_parser.py

履修表の軸と開講番号を読み、占有時間へ変換する。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_normalized`](../timetable_parser.py#L23) | セル文字列 | NFKC正規化し前後空白を除いたstr | 開講番号や軸の全半角差を整える。 |
| [`parse_opening_code`](../timetable_parser.py#L27) | 開講番号str | course_code・academic_year・term・0除外フラグのdict | 先頭2桁から20YY、3桁目からタームを得る。0ならtermはNone。 |
| [`_warning`](../timetable_parser.py#L41) | warningsリスト、code、行番号、メッセージ | None。warningsへdictを追加 | 学生情報等を含めない構造化警告を作る。 |
| [`_context`](../timetable_parser.py#L45) | 前置き行とwarnings | academic_year・semester・termのdict | 年度・学期ラベルの次のセルを解釈し、不一致を検証する。 |
| [`parse_timetable_csv_bytes`](../timetable_parser.py#L70) | 履修表のbytes | TimetableResponse相当のdict | 曜日・時限・開講番号を読んでcourses、busy_slots、未解決等を作る。 |
| [`parse_timetable_csv_bytes.register`](../timetable_parser.py#L137) | セル値・行番号、任意の曜日・時限 | None。外側のcourses・busy・警告等を更新 | 一開講を登録し、番号0除外、表外配置、年度・学期の不一致を確認する。 |

### recommendations.py

実行用の簡易教養カタログと、指定曜限の検索。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`RecommendationError.__init__`](../recommendations.py#L15) | HTTP番号・コード・説明文 | None。例外属性を設定 | カタログ不正・未対応等を上位のHTTP処理へ伝える。 |
| [`_valid_int`](../recommendations.py#L21) | 値、最小値、最大値 | bool | 真偽値を除く整数で、範囲内か確認する。 |
| [`validate_catalog`](../recommendations.py#L25) | schema 3の実行用catalog | None | coursesの6項目、年度・G番号・教養区分・単位・曜限を検証し、不正なら例外。 |
| [`load_catalogs`](../recommendations.py#L70) | 公開カタログルートのPath | 検証済みカタログのlist[dict] | liberal-catalog.jsonを列挙し、archive・sourcesを除外。重複対象や不正配置を拒否する。 |
| [`catalog_metadata`](../recommendations.py#L91) | 検証済みcatalog | 年度・対象・件数・ターム・曜限範囲のdict | 全科目をそのまま配信せず、選択肢に必要な情報を返す。 |
| [`find_catalog`](../recommendations.py#L100) | catalogsと年度・対象を持つcontext | 一致するcatalogのdict | 見つからなければ404用のRecommendationError。 |
| [`recommend_for_slot`](../recommendations.py#L109) | catalog、context、任意のtimetable | 候補・状態・件数・確認状態・説明のdict | 指定枠を含む候補を選ぶ。履修表ありなら全曜限の重複と未確認を除外する。 |
| [`recommend_for_slot.hold`](../recommendations.py#L125) | codeと日本語メッセージ | unknownにしたresultのdict | 時間割の不整合等で判定を保留する内部関数。 |

### recommendation_search.py

卒業の教養不足へ、一候補ずつ仮追加した効果を求める。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_number`](../recommendation_search.py#L12) | Decimal | intまたはfloat | 不足の改善量をJSON向けへ変換する。 |
| [`_name_key`](../recommendation_search.py#L16) | 科目名とprofile | 照合用str | 設定された接尾辞・別名を整えてからNFKCと空白除去を適用する。 |
| [`_liberal_selector`](../recommendation_search.py#L21) | selector | bool | 教養を含む選択条件かをany_ofも含めて調べる。 |
| [`_liberal_only_selector`](../recommendation_search.py#L27) | selector | bool | 教養だけを要求する条件かを調べる。専門との共通条件・総計だけを推薦の起点にしない。 |
| [`_baseline`](../recommendation_search.py#L38) | 評価結果evaluation、採用する条件ID集合 | 必要項目へ絞った条件結果のlist[dict] | 条件ID・状態・最低値・確認済み値・不足等を抜き出す。 |
| [`search_recommendations`](../recommendation_search.py#L45) | catalog、context、report、timetable、profile | baseline・空き時間・確定候補・要確認候補等のdict | 教養充足なら停止。それ以外は候補を一つずつ仮追加して不足減少を評価する。 |
| [`search_recommendations.note`](../recommendation_search.py#L76) | codeと日本語説明 | None。result.messagesを更新 | 同じ説明を重複追加しない内部関数。 |
| [`search_recommendations.matches`](../recommendation_search.py#L100) | 修得済み等の科目existing、候補candidate | bool | 開講番号または正規化した科目名が一致するか確認する。 |

### session_api.py

セッションのHTTP境界。メモリ保持自体はSessionStoreへ任せる。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_origin`](../session_api.py#L21) | Origin文字列 | scheme・小文字ホスト・portのタプル、またはNone | http(s)の有効な接続元かを解釈する。 |
| [`SessionAwareCorsMiddleware.__init__`](../session_api.py#L37) | appと許可Originのlist | None。2種類のCORSを準備 | 従来APIは資格情報なし、session経路は資格情報ありへ分ける。 |
| [`SessionAwareCorsMiddleware.__call__`](../session_api.py#L47) | scope・receive・send | None。選んだCORSアプリを実行 | パスがsession配下かで適用するCORSを切り替える。 |
| [`_cookie_name`](../session_api.py#L53) | Request | Cookie名str | HTTPSは__Host-credit_session、localhost等のHTTPはcredit_session。 |
| [`guard_session_request`](../session_api.py#L57) | Request、本文を許可するか | None | HTTPS／localhost、専用ヘッダー、接続元、本文を確認。不正ならSessionError。 |
| [`workspace_headers`](../session_api.py#L81) | Request | Cookie識別子・CSRF・更新番号intのタプル | revisionの形式と重複を確認する。CSRF値の一致はストア側で検証する。 |
| [`create_session`](../session_api.py#L95) | Request | SessionResponseを含むJSONResponse | 作成または既存の再取得。新規時だけCookieを設定し、有効期限は延長しない。 |
| [`get_session`](../session_api.py#L106) | Request | 有効期限・CSRF等のdict | Cookieで現在のセッションメタデータを取得する。なければ401。 |
| [`end_session`](../session_api.py#L112) | Request | endedを返すJSONResponse | CSRF確認後に当該保持データとCookieを削除する。 |
| [`get_workspace`](../session_api.py#L124) | Request | 成績・履修表を含むworkspaceのdict | 有効なCookieから保持結果を復元する。新規作成はしない。 |

### session_store.py

固定期限のメモリストア。SQL・ファイルI/Oを使わない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`SessionError.__init__`](../session_store.py#L23) | HTTP番号・コード・日本語メッセージ | None。例外属性を設定 | HTTP境界へ渡す保持・期限・検証エラーを表す。 |
| [`SessionSettings.__post_init__`](../session_store.py#L38) | 設定オブジェクト自身 | None | 正の整数設定と、全体容量が個別容量以上かを検証する。 |
| [`SessionSettings.from_environ`](../session_store.py#L47) | 任意の環境変数辞書 | SessionSettingsオブジェクト | TTL・件数・個別容量・全体容量を環境変数または既定から取る。 |
| [`SessionSettings.from_environ.positive`](../session_store.py#L50) | 環境変数名と既定値 | 正のint | ASCIIの数字であることを確認する内部関数。 |
| [`_Session.data_size`](../session_store.py#L71) | セッション自身 | int | 保持する成績JSONと履修表JSONのバイト数を合計するproperty。 |
| [`SessionStore.__init__`](../session_store.py#L78) | 任意の設定・時計関数・トークン生成関数 | None。空のストアを作る | records・保持量・ロックを準備。時計等の差替えはテストにも使う。 |
| [`SessionStore._key`](../session_store.py#L89) | Cookie識別子strまたはNone | SHA-256の文字列、形式不正ならNone | Cookie原文をストアのキーにしない。 |
| [`SessionStore._purge`](../session_store.py#L94) | 現在の経過時刻now | 削除した件数int | 固定期限に達したレコードを除去する。呼出し元でロックを管理する。 |
| [`SessionStore._remove`](../session_store.py#L101) | 内部キーstr | None | レコードを取り除き、保持バイト数を差し引く。 |
| [`SessionStore._record`](../session_store.py#L104) | Cookie識別子 | 内部キー・セッション箱・現在時刻のタプル | 失効を掃除し、対象がなければ401。 |
| [`SessionStore._check_update`](../session_store.py#L113) | セッション箱、CSRF、revision | None | CSRFを安全に比較し、更新番号不一致を409にする。 |
| [`SessionStore._workspace`](../session_store.py#L122) | セッション箱と現在時刻 | workspaceのdict | 保存JSONを独立した辞書へ戻し、メタデータ・更新番号とまとめる。 |
| [`SessionStore._view`](../session_store.py#L127) | セッション箱と現在時刻 | 有効期限・CSRF等のdict | 残り秒数を切り上げて返す。Cookie原文は含めない。 |
| [`SessionStore.create_or_resume`](../session_store.py#L132) | 任意のCookie識別子 | 新Cookie値またはNone、とメタデータdictのタプル | 有効なら同じ期限のまま取得。新規だけランダムな識別子とCSRFを作る。 |
| [`SessionStore.get`](../session_store.py#L154) | Cookie識別子 | セッションメタデータdict | 有効なものだけ取得し、期限は延長しない。 |
| [`SessionStore.workspace`](../session_store.py#L159) | Cookie識別子 | workspaceのdict | 有効セッションの成績と履修表を取得する。 |
| [`SessionStore.checked_workspace`](../session_store.py#L164) | Cookie識別子、CSRF、revision | workspaceのdict | 更新確認後のスナップショットを取得する。 |
| [`SessionStore.assert_current`](../session_store.py#L170) | Cookie識別子、CSRF、revision | None | JSONを復元せず、現在も同じ有効状態かだけ確認する。 |
| [`SessionStore.begin_update`](../session_store.py#L175) | Cookie識別子、CSRF、revision、kind | 先へ進めた更新番号int | 旧同種データを先に消す。個別削除にも使用する。 |
| [`SessionStore.commit`](../session_store.py#L187) | Cookie識別子、CSRF、pending revision、kind、解析済みdict | 保持確定後のworkspaceのdict | dictをJSON bytesへ変え、期限・更新番号・個別／全体容量を確認して保持する。 |
| [`SessionStore.end`](../session_store.py#L204) | Cookie識別子とCSRF | None | 当該セッションを終了する。別利用者のレコードは消さない。 |
| [`SessionStore.cleanup`](../session_store.py#L212) | 引数なし | 削除した件数int | ロックを取得して期限切れを掃除する。 |
| [`SessionStore.clear`](../session_store.py#L216) | 引数なし | None | ストア全体の保持を空にする。停止・テスト用。 |
| [`SessionStore.cleanup_loop`](../session_store.py#L221) | 引数なし | 停止されるまで繰り返す非同期処理 | 通常30秒、TTLが短ければそれ以下の間隔でcleanupを呼ぶ。 |

### catalog_import.py

公開PDFの抽出専用。通常のHTTP処理では実行しない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`compact`](../catalog_import.py#L19) | 文字列またはNone | NFKC正規化して空白を除いたstr | 公開PDFのセル・見出し・番号の照合を助ける。 |
| [`extract_offering_rows`](../catalog_import.py#L23) | PDFのPath、年度のsource設定、任意の進捗関数 | recordsのlistとauditのdictのタプル | 表の16列と本文中のG番号の対応を検証して返す。結果ファイルの保存は呼出し元が行う。 |

### offering_catalog.py

抽出済み公開セルから開講データを作る。実行用catalogとは別に調査用の詳しい形式も扱う。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`display_text`](../offering_catalog.py#L19) | 表示用セル文字列 | str | 全半角・日本語途中の改行・連続空白を整える。 |
| [`parse_terms`](../offering_catalog.py#L25) | 公開資料の開講時期str | タームintのlistまたはNone | 第1学期なら1・2等へ展開。解釈不能はNone。 |
| [`parse_meetings`](../offering_catalog.py#L37) | 曜日と時限の文字列 | weekday・periodのlist[dict]またはNone | 明示的な組合せだけ展開。複数曜日と複数時限の対応を推測しない。 |
| [`parse_credits`](../offering_catalog.py#L57) | 単位数セルstr | 正のint・float、またはNone | 公開カタログの単位を解釈する。成績CSVの0以上という受入れ条件とは異なる。 |
| [`normalize_offering`](../offering_catalog.py#L67) | cells・sourceを持つrecordと年度config | 詳細な一開講のdict | 名前・単位・時期・曜限・対象者・未確定理由・出典等へ整理する。 |
| [`assess_audience`](../offering_catalog.py#L133) | 主聴講対象文字列と対象設定 | 対象整合性のstatus・reason等のdict | 明示的な対象除外や複雑条件を確認する。関数は旧学年指定にも対応するが現行共通候補ではgrade=None。 |
| [`assess_for_target`](../offering_catalog.py#L175) | 正規化開講offeringと対象設定 | 候補・要確認・除外と理由のdict | データ準備状態と主聴講対象との整合をまとめる。履修許可の確定ではない。 |
| [`build_catalog`](../offering_catalog.py#L191) | 抽出records、config、原本SHA-256 | 詳細catalog・対象view・qualityの3つのdict | G開講を正規化し、重複番号を拒否し、件数・理由等の品質情報を作る。 |
| [`validate_catalog`](../offering_catalog.py#L232) | offeringsを持つschema 1の詳細catalog | None | 詳細形式の年度・番号・ready条件・曜限範囲・重複を確認する。recommendations側の同名関数とは入力形式が違う。 |
| [`common_offerings`](../offering_catalog.py#L255) | 詳細offeringsのlist、対象設定 | 採用条件に合う開講のlist[dict] | 全学部向け・明確な曜限・月〜金1〜5限を条件とし、学年では絞らない。 |
| [`coverage_features`](../offering_catalog.py#L266) | 詳細な一開講offering | 曜限とターム別区分を表すtupleのset | 代表選定が保持すべき特徴を取り出す。 |
| [`representative_offerings`](../offering_catalog.py#L273) | 採用可能なofferings | 代表開講のlist[dict] | 未網羅の特徴を多く補うものから採用し、不要な代表を減らす。最少数の保証はない。 |
| [`summarize_coverage`](../offering_catalog.py#L291) | offeringsのlist | 件数・100枠の網羅・不足枠・行列のdict | 曜日別100枠と、曜日をまとめたターム×時限の件数を区別する。 |
| [`compact_course`](../offering_catalog.py#L312) | 詳細な一開講offering | 実行用6項目のdict | ターム別曜限が一致することを確かめ、出典等を省いた一科目を作る。 |
| [`build_compact_catalog`](../offering_catalog.py#L324) | 詳細catalog、config、selection | schema 3の簡易catalogと網羅reportのタプル | allまたはrepresentativeを選ぶ。CLIはallだが、この関数の既定はrepresentative。 |

### api_contracts/specification.py

型とHTTP経路の情報を機械可読仕様へ変える。通常APIの受付コードではない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_upload_fields`](../api_contracts/specification.py#L15) | search・slot・timetableの指定 | multipart入力のJSON Schema dict | 各APIで使うファイル・数値・対象ID・容量等を定義する。 |
| [`_upload_fields.file`](../api_contracts/specification.py#L16) | 説明str | 一ファイル欄のSchema dict | binaryとサイズ上限を付ける内部関数。 |
| [`_errors`](../api_contracts/specification.py#L97) | upload・profile・recommendation・catalogの指定 | HTTP番号からコードlistを引くdict | 従来APIに必要なエラー定義を集める。 |
| [`_session_errors`](../api_contracts/specification.py#L134) | bootstrap・endの指定 | セッション用エラー定義dict | 接続元・専用ヘッダー・期限・作成上限・CSRF等を定義する。 |
| [`_workspace_errors`](../api_contracts/specification.py#L160) | upload・recommendationの指定 | workspace用エラー定義dict | 競合、保持容量、検索条件等のエラーを追加する。 |
| [`json_schemas`](../api_contracts/specification.py#L201) | 引数なし | $defs等を持つSchema集のdict | Pydantic応答型から作るSchemaへ、入力・ヘッダー定義を加える。 |
| [`response_schema`](../api_contracts/specification.py#L222) | 応答型名、任意のSchema集 | その応答型を検証するSchema dict | 対応型を$refで指定し、参照先の$defsも含める。 |
| [`_openapi_refs`](../api_contracts/specification.py#L229) | dict・list等のSchema構造 | 参照先を書換えた構造 | $defsへの参照をOpenAPIのcomponents/schemasへ再帰変換する。 |
| [`openapi_document`](../api_contracts/specification.py#L239) | 任意のSchema集 | OpenAPI 3.1のdict | OPERATIONSからURL・入力・応答・エラー・Cookie記述を作る。 |
| [`openapi_document.response`](../api_contracts/specification.py#L265) | 応答モデル名と説明 | 一HTTP応答の仕様dict | JSON形式の型とno-storeのヘッダー定義を付ける内部関数。 |

### api_contracts/typescript.py

生成するのは型宣言の文字列で、ブラウザーの動作コードではない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_literal`](../api_contracts/typescript.py#L10) | JSON化できる値 | JSON表記のstr | 文字列リテラルなどをTypeScriptへ安全に出力する。 |
| [`schema_type`](../api_contracts/typescript.py#L14) | 一型のJSON Schema dict | TypeScriptの型表記str | object・array・null・Union等を再帰変換し、未対応構造を黙ってanyにしない。 |
| [`typescript_declarations`](../api_contracts/typescript.py#L61) | $defsを持つSchema集 | api.d.ts全体のstr | 全型とApiOperationsを宣言する。ファイル保存は生成スクリプトが行う。 |

### api_contracts/examples.py

架空値とローカルASGI呼出しによる応答例生成。通常サーバーの処理へ混ぜない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_csv`](../api_contracts/examples.py#L33) | 架空の行list[list[str]] | UTF-8 BOM付きのCSV bytes | メモリ内でCSVを組み立てる。 |
| [`_shared_sample`](../api_contracts/examples.py#L39) | 許可した架空サンプルの名前 | 架空CSV bytes | 氏名ラベルが架空で番号がT00000000か確認する。利用者CSVパスは受け付けない。 |
| [`fictional_grades`](../api_contracts/examples.py#L51) | 任意の架空grade・pending指定 | 架空の成績CSV bytes | 修得・未修得・未確定・未知区分等を生成する。 |
| [`fictional_timetable`](../api_contracts/examples.py#L68) | empty・missing_code等の指定 | 架空の履修表CSV bytes | 時間割の境界ケースをメモリで作る。 |
| [`fictional_catalog`](../api_contracts/examples.py#L94) | 引数なし | 架空のschema 3カタログdict | 契約確認用の3候補を作る。 |
| [`multipart`](../api_contracts/examples.py#L108) | 文字列fieldsとファイルbytes | httpx2へ渡すmultipart用list | 文字列部分とファイル部分を分けて表す。 |
| [`collect_examples`](../api_contracts/examples.py#L113) | 引数なし | Exampleオブジェクトのlist | 成績・時間割・推薦・エラーにセッション例も加える。 |
| [`collect_examples.record`](../api_contracts/examples.py#L121) | 例の名前・HTTPメソッド・パス・型・期待番号等 | None。examplesへ追加 | 従来APIをASGI呼出しし、ステータスと非Cookie等を確認する。 |
| [`collect_session_examples`](../api_contracts/examples.py#L226) | 引数なし | セッションのExampleのlist | 固定時計と架空トークンの独立ストアでメタデータ例を作る。 |
| [`collect_session_examples.fictional_token`](../api_contracts/examples.py#L231) | 引数なし | 43文字の架空トークンstr | 実行のたびに応答例が変わらないようにする。実運用の識別子生成には使わない。 |
| [`collect_session_examples.record`](../api_contracts/examples.py#L241) | 例の名前・メソッド・型・期待番号等 | 取得したbodyのdict | 応答例を保存対象リストへ加え、後続操作用に本文も返す。 |
| [`collect_workspace_examples`](../api_contracts/examples.py#L273) | 引数なし | workspace・保持結果検索のExampleのlist | 成績・履修表を保持し、復元・クリア・競合等の応答を集める。 |
| [`collect_workspace_examples.token`](../api_contracts/examples.py#L276) | 引数なし | 固定形式の架空トークンstr | workspace例の再現性を保つ内部関数。 |
| [`collect_workspace_examples.mutation_headers`](../api_contracts/examples.py#L288) | 引数なし | CSRFと更新番号を持つヘッダーdict | 現在の架空workspaceから、次の操作の確認情報を取る。 |
| [`collect_workspace_examples.record`](../api_contracts/examples.py#L295) | 例の名前・メソッド・パス・型・期待番号等 | None。examplesへ追加 | workspaceの実応答を確認して記録用リストへ加える。 |

### scripts/build_api_contract.py

契約の生成・差分確認CLI。--checkは配布ファイルを書き換えない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`_json`](../scripts/build_api_contract.py#L25) | JSON化する値 | 整形済みJSON str | UTF-8で扱う非ASCII表記を維持し、NaNを禁止する。 |
| [`build_artifacts`](../scripts/build_api_contract.py#L29) | 引数なし | 相対ファイル名から生成内容strを引くdict | 型・Schemaと実ASGI応答例を照合して生成物をメモリに作る。 |
| [`main`](../scripts/build_api_contract.py#L69) | 引数なし。コマンドラインを読む | 終了コードint | 通常は生成物をcontractsへ書き、--checkなら現行ファイルと照合する。差分は1、成功は0。 |

### scripts/build_liberal_catalog.py

公開カタログの生成CLI。学生データは入力しない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`write_json`](../scripts/build_liberal_catalog.py#L19) | 保存先Pathと公開データ | None。JSONファイルへ書込み | 親フォルダーを作り、読みやすく整形して保存する。 |
| [`json_digest`](../scripts/build_liberal_catalog.py#L24) | JSON化可能な公開データ | SHA-256のstr | キー順を揃えた内容から、抽出キャッシュ整合確認用の値を作る。 |
| [`write_summary`](../scripts/build_liberal_catalog.py#L29) | 年度folder、config、網羅report | None。調査READMEを更新 | 採用件数・曜限件数・候補なし枠・制約をまとめる。 |
| [`archive_legacy`](../scripts/build_liberal_catalog.py#L66) | 年度folderと旧ファイル名 | None。必要ならarchiveへ移動 | 旧版を完全削除せず、重複時は内容ハッシュ付き名称で保持する。 |
| [`main`](../scripts/build_liberal_catalog.py#L79) | 引数なし。年度・download・extract-only・selection等のCLI指定 | None。公開JSON・抽出キャッシュ等を必要に応じ生成 | 公開PDF取得と版・ハッシュ照合、抽出、簡易カタログ生成を取りまとめる。 |

### scripts/check_localhost_uploads.py

起動済みlocalhostを使う開発用確認。入力・応答本文をログへ出さない。

| 関数とソース位置 | 受け取る値 | 返す値・作用 | 目的と読取上の注意 |
| --- | --- | --- | --- |
| [`encode`](../scripts/check_localhost_uploads.py#L43) | 架空の行list、文字コード、改行 | CSV bytes | 指定した文字コード・改行の架空CSVを作る。 |
| [`example_rows`](../scripts/check_localhost_uploads.py#L49) | 同梱架空サンプル名と文字コード | 前置き4行・19列に揃えた行list | この確認用の形式へ整える。成績パーサーの行数を固定する処理ではない。 |
| [`example_rows.pad`](../scripts/check_localhost_uploads.py#L60) | 一行list | 19列へ空欄を補ったlist | 確認用のメタデータ行を整える内部関数。 |
| [`change`](../scripts/check_localhost_uploads.py#L76) | 架空の行list、科目名、変更フィールド | None。該当行を更新 | 合否・単位等の境界ケースを作る。 |
| [`add_course`](../scripts/check_localhost_uploads.py#L82) | 架空の行list、科目名・区分・単位 | None。架空科目行を追加 | 元サンプルを増やした可変行数等のケースを作る。 |
| [`build_cases`](../scripts/check_localhost_uploads.py#L91) | 引数なし | Caseオブジェクトのlist | 架空入力と期待値の組合せを作る。 |
| [`build_cases.add`](../scripts/check_localhost_uploads.py#L96) | ケース名、行、期待する要件状態、任意の期待値 | None。casesへ追加 | CSVをbytesへ変えて確認ケースを登録する内部関数。 |
| [`public_result`](../scripts/check_localhost_uploads.py#L247) | APIのreport dict | 検証用に再配置したdict | 内部の比較用。科目名・成績等を含む部分もあり、この戻り値全体をログへ出すものではない。 |
| [`verify`](../scripts/check_localhost_uploads.py#L266) | actual、部分期待値expected、比較位置path | None | 期待するキー・値を再帰確認し、不一致位置だけを例外へ示す。 |
| [`check_case`](../scripts/check_localhost_uploads.py#L279) | Case、実HTTP番号、report | None | HTTP番号・期待値・表示文・三値・総合の整合を確認する。 |
| [`run`](../scripts/check_localhost_uploads.py#L307) | localhostのHTTPルートURL | 終了コードint | 配信ファイル一致と架空CSVのAPI確認を実行。ログは選択した判定概要等だけに限定する。 |

## 2. 関数へ渡す主なデータの箱

データを持つクラスは関数と区別する。`@dataclass`では初期化メソッド等が自動生成されるため、ソースに`def __init__`がない場合もある。

| 型 | 主な値 | 意味 |
| --- | --- | --- |
| `server.MultipartPart` | headers、field_name、capture、data等 | 受信途中の一部分。dataは変更できるbytearray |
| `server.ReportUpload` | raw、fields | 成績等の単一ファイルとフォーム文字列 |
| `server.MultipartUpload` | files、fields | 複数ファイルにも対応する汎用受信結果 |
| `session_store.SessionSettings` | ttl_seconds、max_sessions、max_data_bytes等 | 期限・件数・保持容量の設定 |
| `session_store._Session` | created_at、csrf_token、revision、report_json、timetable_json | 一利用者の短期状態。parsed JSONをbytesで保持 |
| `api_contracts.examples.Example` | name、method、path、status、model、body | 架空HTTP応答の一事例 |
| `scripts.check_localhost_uploads.Case` | name、raw、expected、http_status | 架空CSVと期待値の一ケース |

## 3. `api_contracts/models.py`の応答型

以下はPydanticモデルとTypedDictによる型定義で、JSONの形を宣言するもの。サーバーの保持領域や学務判定の処理ではない。項目欄はそのクラスで宣言したフィールドで、親クラスのフィールドも継承する。型の詳細・制約はリンク先で確認できる。

`ErrorDetails`・`ApiErrorBody`はTypedDictで、通常のPython辞書のキーと値の型を表す。大半の他の型は`ContractModel`を継承するPydanticモデル。TypedDictを書くだけで、実行中の辞書を自動検証するわけではない。

例：`Count`は0以上の整数、`Credit`は0以上の数値、`Judgment`は三値の文字列。`str | None`は値なしも許す。`NotRequired`はキー自体を省略できることを表し、値が`None`でよいという意味とは異なる。

| 型とソース位置 | 継承元 | 宣言する主なフィールド |
| --- | --- | --- |
| [`ContractModel`](../api_contracts/models.py#L29) | `BaseModel` | 個別フィールドなし。共通設定を持つ |
| [`HealthResponse`](../api_contracts/models.py#L33) | `ContractModel` | `status` |
| [`RuleRequirement`](../api_contracts/models.py#L37) | `ContractModel` | `requirement_id`、`title`、`rule_status` |
| [`RuleProfile`](../api_contracts/models.py#L43) | `ContractModel` | `profile_id`、`institution`、`faculty`、`program`、`admission_year`、`policy_notes`、`requirements`、`implemented_requirement_ids` |
| [`RuleProfilesResponse`](../api_contracts/models.py#L54) | `ContractModel` | `profiles`、`default_profile_id` |
| [`Curriculum`](../api_contracts/models.py#L59) | `ContractModel` | `institution`、`faculty`、`program`、`admission_year`、`rules_version`、`policy_notes` |
| [`Student`](../api_contracts/models.py#L68) | `ContractModel` | `name`、`student_number`、`affiliation`、`grade` |
| [`MajorSummary`](../api_contracts/models.py#L75) | `ContractModel` | `major`、`earned_credits`、`unconfirmed_credits`、`course_count` |
| [`CategorySummary`](../api_contracts/models.py#L82) | `MajorSummary` | `source_category`、`field`、`detail`、`passed_count`、`unconfirmed_count` |
| [`ReportSummary`](../api_contracts/models.py#L90) | `ContractModel` | `course_count`、`passed_count`、`unconfirmed_count`、`unknown_credit_count`、`earned_credits`、`unconfirmed_credits`、`majors`、`categories` |
| [`TranscriptCourse`](../api_contracts/models.py#L101) | `ContractModel` | `no`、`sequence`、`row_number`、`code`、`course_code`、`name`、`source_category`、`normalized_name`、`major`、`field`、`detail`、`curriculum_area`、`classification_status`、`course_group`、`requirement_code`、`catalog_course_id`、`classification_reason_code`、`requirement_type`、`field_codes`、`level`、`credits`、`status`、`result`、`source_result`、`year`、`earned_year`、`term`、`earned_term` |
| [`SourceRef`](../api_contracts/models.py#L132) | `ContractModel` | `document_id`、`printed_pages`、`pdf_pages`、`section` |
| [`ResolvedSource`](../api_contracts/models.py#L139) | `SourceRef` | `title`、`url`、`section` |
| [`Caveat`](../api_contracts/models.py#L145) | `ContractModel` | `id`、`status`、`message` |
| [`EvaluationInputContext`](../api_contracts/models.py#L151) | `ContractModel` | `residence_years`、`residence_years_source`、`student_grade_year` |
| [`EvaluationContext`](../api_contracts/models.py#L157) | `EvaluationInputContext` | `displayed_requirement_ids` |
| [`ConditionBase`](../api_contracts/models.py#L161) | `ContractModel` | `id`、`label`、`status`、`reason_code`、`description` |
| [`CreditValues`](../api_contracts/models.py#L169) | `ConditionBase` | `minimum_credits`、`confirmed_credits`、`confirmed_credit_shortfall`、`has_uncertain_candidate` |
| [`CreditCondition`](../api_contracts/models.py#L178) | `CreditValues` | `applied_credit_caps` |
| [`NamedCourseCondition`](../api_contracts/models.py#L182) | `CreditValues` | `matched_course_names` |
| [`SharedSurplusCondition`](../api_contracts/models.py#L186) | `CreditValues` | `source_surplus_credits` |
| [`ResidualCreditCondition`](../api_contracts/models.py#L190) | `CreditCondition` | `confirmed_area_credits`、`allocated_to_prior_conditions`、`allocated_by_condition` |
| [`RequiredCourseResult`](../api_contracts/models.py#L196) | `ContractModel` | `catalog_course_id`、`name`、`status`、`reason_code`、`minimum_credits`、`confirmed_credits`、`confirmed_credit_shortfall`、`has_uncertain_candidate`、`source_refs`、`description` |
| [`RequiredCoursesCondition`](../api_contracts/models.py#L209) | `ConditionBase` | `required_course_count`、`satisfied_course_count`、`missing_course_names`、`unknown_course_names`、`course_results` |
| [`ResidenceCondition`](../api_contracts/models.py#L217) | `ConditionBase` | `minimum_years`、`confirmed_years`、`value_source` |
| [`UnsupportedCondition`](../api_contracts/models.py#L223) | `ConditionBase` | `status`、`reason_code` |
| [`Evaluation`](../api_contracts/models.py#L234) | `ContractModel` | `requirement_id`、`title`、`profile_id`、`status`、`description`、`advisory_only`、`rule_status`、`evidence_status`、`input_context`、`conditions`、`source_refs`、`sources`、`caveat_ids`、`caveats` |
| [`ReportResponse`](../api_contracts/models.py#L251) | `ContractModel` | `schema_version`、`curriculum`、`student`、`summary`、`courses`、`warnings`、`evaluations`、`evaluation_context` |
| [`TimetableContext`](../api_contracts/models.py#L262) | `ContractModel` | `academic_year`、`semester`、`term` |
| [`DisplayContext`](../api_contracts/models.py#L268) | `ContractModel` | `academic_year`、`term` |
| [`TimetableSlot`](../api_contracts/models.py#L273) | `ContractModel` | `weekday`、`period` |
| [`TimetableCourse`](../api_contracts/models.py#L278) | `DisplayContext` | `course_code`、`slots` |
| [`BusySlot`](../api_contracts/models.py#L283) | `DisplayContext, TimetableSlot` | 個別フィールドなし。共通設定を持つ |
| [`TimetableWarning`](../api_contracts/models.py#L287) | `ContractModel` | `code`、`row_number`、`message` |
| [`OutsideGridCourse`](../api_contracts/models.py#L293) | `ContractModel` | `course_code`、`row_number`、`reason_code` |
| [`MissingCourseCode`](../api_contracts/models.py#L299) | `TimetableSlot` | `course_code`、`row_number`、`reason_code` |
| [`TimetableResponse`](../api_contracts/models.py#L305) | `ContractModel` | `schema_version`、`format`、`context`、`display_contexts`、`represented_weekdays`、`represented_periods`、`courses`、`busy_slots`、`excluded_term_zero_course_count`、`policy_notes`、`unresolved_courses`、`ready_for_recommendation`、`warnings` |
| [`RecommendationCatalog`](../api_contracts/models.py#L321) | `ContractModel` | `academic_year`、`profile_id`、`program`、`course_count`、`terms`、`weekdays`、`periods` |
| [`RecommendationCatalogsResponse`](../api_contracts/models.py#L331) | `ContractModel` | `schema_version`、`catalogs` |
| [`RecommendationContext`](../api_contracts/models.py#L336) | `DisplayContext` | `profile_id` |
| [`SlotContext`](../api_contracts/models.py#L340) | `RecommendationContext` | `weekday`、`period` |
| [`OfferingSlot`](../api_contracts/models.py#L345) | `ContractModel` | `weekday`、`period` |
| [`Candidate`](../api_contracts/models.py#L350) | `ContractModel` | `course_code`、`name`、`credits`、`category`、`terms`、`schedule` |
| [`ApiMessage`](../api_contracts/models.py#L359) | `ContractModel` | `code`、`message` |
| [`SlotCounts`](../api_contracts/models.py#L364) | `ContractModel` | `matching`、`returned`、`excluded_overlap`、`excluded_unconfirmed`、`excluded_registered` |
| [`SlotChecks`](../api_contracts/models.py#L372) | `ContractModel` | `timetable`、`earned_credits`、`requirements`、`enrollment` |
| [`SlotRecommendationsResponse`](../api_contracts/models.py#L379) | `ContractModel` | `schema_version`、`context`、`basis`、`status`、`candidates`、`counts`、`checks`、`messages` |
| [`BaselineCondition`](../api_contracts/models.py#L390) | `ContractModel` | `id`、`label`、`status`、`minimum_credits`、`confirmed_credits`、`confirmed_credit_shortfall`、`has_uncertain_candidate` |
| [`CandidateBenefit`](../api_contracts/models.py#L400) | `ContractModel` | `condition_id`、`label`、`before_shortfall`、`after_shortfall`、`reduced_credits`、`before_status`、`after_status` |
| [`SearchCandidate`](../api_contracts/models.py#L410) | `Candidate` | `benefits`、`uncertain_benefits`、`review_reasons` |
| [`SearchCounts`](../api_contracts/models.py#L416) | `ContractModel` | `catalog_in_term`、`excluded_earned`、`excluded_registered`、`excluded_overlap`、`excluded_unconfirmed_time`、`excluded_no_benefit`、`returned`、`review_required` |
| [`SearchChecks`](../api_contracts/models.py#L427) | `ContractModel` | `timetable`、`earned_credits`、`requirements`、`enrollment` |
| [`RecommendationSearchResponse`](../api_contracts/models.py#L434) | `ContractModel` | `schema_version`、`context`、`target_requirement_id`、`status`、`baseline`、`free_slots`、`candidates`、`review_candidates`、`counts`、`checks`、`messages` |
| [`ErrorDetails`](../api_contracts/models.py#L448) | `TypedDict` | `field`、`columns`、`profile_id` |
| [`ApiErrorBody`](../api_contracts/models.py#L455) | `TypedDict` | `code`、`message`、`details` |
| [`ErrorResponse`](../api_contracts/models.py#L462) | `ContractModel` | `error` |
| [`SessionResponse`](../api_contracts/models.py#L466) | `ContractModel` | `schema_version`、`status`、`csrf_token`、`ttl_seconds`、`expires_in_seconds` |
| [`SessionEndedResponse`](../api_contracts/models.py#L475) | `ContractModel` | `schema_version`、`status` |
| [`SessionWorkspaceResponse`](../api_contracts/models.py#L480) | `ContractModel` | `schema_version`、`revision`、`session`、`report`、`timetable` |

## 4. 読むときの境界

- `academic_rules.RuleDataError`は規則JSONの不正、`RuleProfileNotFoundError`は対象IDの未対応。通常の学生の不合格を表す例外ではない。
- `api_contracts/__init__.py`には説明文だけがあり、呼び出す関数はない。
- ラムダ式は名前のない短い関数。たとえば時計を差し替える`lambda: now[0]`は、呼ぶたびに現在のテスト時刻を一つ返す。
- `api_contracts`と`scripts`は開発用の読取り・生成・検証を含む。公開カタログや架空応答例のファイル書込みと、アップロード学生データの非保存を混同しない。
- この一覧は既存コードの説明であり、SQLite・共有評価の実装を再開するものではない。

参考：上記18ファイルの名前付き関数・メソッド214件は、ソースの構文木から存在・行番号・記載漏れを照合した。テスト関数の全列挙は対象外とし、読む入口は本冊第13節へまとめた。
