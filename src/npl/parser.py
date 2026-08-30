"""NPL 递归下降解析器：token 流 → AST。

只负责语法层（NAR-001）与结构层错误（NAR-010 缺版本头 / NAR-011 顶层重名 / NAR-012 块内重复字段）。
语义校验（NAR-002/003/004/013/041）见 validator.py。
"""
from . import ast_nodes as ast
from .errors import NPLSyntaxError
from .lexer import TokenType as T
from .lexer import tokenize

SECTION_WORDS = {"knows", "believes", "suspects", "does_not_know", "intends", "goal"}
TRAIT_WORDS = {"personality", "emotion"}
RELATION_WORD = "relations"          # v0.5：character 块内有向态度小节
WORLD_WORDS = "location/time/fact/entity/process"
NEST_VERBS = ("knows", "does_not_know", "believes")
INFO_WORDS = "truth/known_by/unknown_to/suspected_by/public"
SCENE_WORDS = ("pov/location/world_time/flashback/participants/access/events/"
               "information_changes/dramatic_goal/emotional_arc/"
               "motifs/foreshadows/withholds/misdirects/relation_changes")
INTENT_KINDS = ("goal", "forbid", "pacing")
PACING_KINDS = ("suspicion_up",)
STYLE_FIELDS = ("desc", "sentence_max", "emotion_naming", "sensory",
                "dialogue_gaps", "rule")
MOTIF_ROLES = ("introduce", "recurrence", "final")


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    # ---------- 基础工具 ----------
    def peek(self, k=0):
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def advance(self):
        tok = self.toks[self.i]
        if tok.type != T.EOF:
            self.i += 1
        return tok

    def check(self, type_, value=None):
        tok = self.peek()
        return tok.type == type_ and (value is None or tok.value == value)

    def accept(self, type_):
        if self.check(type_):
            return self.advance()
        return None

    @staticmethod
    def _describe(tok):
        if tok.type == T.EOF:
            return "文件结尾（可能缺少 '}'）"
        return repr(tok.value if tok.value is not None else tok.type)

    def expect(self, type_, what=""):
        tok = self.peek()
        if tok.type != type_:
            expected = what or type_
            raise NPLSyntaxError(tok.line, f"期待 {expected}，得到 {self._describe(tok)}")
        return self.advance()

    def expect_ident(self, what="标识符"):
        tok = self.peek()
        if tok.type != T.IDENT:
            raise NPLSyntaxError(tok.line, f"期待{what}，得到 {self._describe(tok)}")
        return self.advance()

    def skip_newlines(self):
        while self.check(T.NEWLINE):
            self.advance()

    def end_of_stmt(self):
        """语句终结：换行，或紧随 '}' / EOF（允许末条语句不换行）。"""
        if self.check(T.NEWLINE):
            self.advance()
            self.skip_newlines()
        elif self.check(T.RBRACE) or self.check(T.EOF):
            pass
        else:
            tok = self.peek()
            raise NPLSyntaxError(tok.line, f"语句结束后期待换行或 '}}'，得到 {self._describe(tok)}")

    # ---------- 顶层 ----------
    def parse_program(self):
        self.skip_newlines()
        tok = self.peek()
        if not self.check(T.VERSION):
            raise NPLSyntaxError(tok.line, "缺少版本头（首行必须是 npl@0.1 或 npl@0.2）", code="NAR-010")
        version = self.advance().value
        if version not in ("npl@0.1", "npl@0.2"):
            raise NPLSyntaxError(tok.line,
                                 f"不支持的语言版本 '{version}'（支持 npl@0.1 / npl@0.2）",
                                 code="NAR-010")
        program = ast.Program(version=version)
        seen_top = set()
        self.skip_newlines()
        while not self.check(T.EOF):
            tok = self.peek()
            word = tok.value
            if word == "import":
                decl = self.parse_import()
                if seen_top:
                    raise NPLSyntaxError(decl.line,
                                         "import 必须位于其他顶层声明之前（v0.2）", code="NAR-001")
                program.imports.append(decl)
                self.skip_newlines()
                continue
            if word == "world":
                if "world" in seen_top:
                    raise NPLSyntaxError(tok.line, "重复的 world 声明（一个程序最多一个 world 块）", code="NAR-011")
                seen_top.add("world")
                program.world = self.parse_world()
            elif word == "character":
                decl = self.parse_character()
                key = ("character", decl.name)
                if key in seen_top:
                    raise NPLSyntaxError(decl.line, f"重复声明人物 '{decl.name}'", code="NAR-011")
                seen_top.add(key)
                program.characters.append(decl)
            elif word == "information":
                decl = self.parse_information()
                key = ("information", decl.name)
                if key in seen_top:
                    raise NPLSyntaxError(decl.line, f"重复声明信息对象 '{decl.name}'", code="NAR-011")
                seen_top.add(key)
                program.informations.append(decl)
            elif word == "scene":
                decl = self.parse_scene()
                key = ("scene", decl.title)
                if key in seen_top:
                    raise NPLSyntaxError(decl.line, f"重复的场景标题 '{decl.title}'", code="NAR-011")
                seen_top.add(key)
                program.scenes.append(decl)
            elif word == "render":
                if "render" in seen_top:
                    raise NPLSyntaxError(tok.line, "重复的 render 声明", code="NAR-011")
                seen_top.add("render")
                program.render = self.parse_render()
            elif word == "style":
                decl = self.parse_style_decl()
                key = ("style", decl.key)
                if key in seen_top:
                    raise NPLSyntaxError(decl.line, f"重复的风格声明 '{decl.key}'", code="NAR-011")
                seen_top.add(key)
                program.styles.append(decl)
            elif word == "intent":
                if "intent" in seen_top:
                    raise NPLSyntaxError(tok.line, "重复的 intent 声明", code="NAR-011")
                seen_top.add("intent")
                program.intents.extend(self.parse_intent_block())
            else:
                raise NPLSyntaxError(tok.line,
                                     f"未知的顶层声明 '{word}'（v0.1 支持 world/character/information/scene/render/style/intent）")
            self.skip_newlines()
        return program

    # ---------- import（v0.2） ----------
    def parse_import(self):
        tok = self.advance()          # 'import'
        path_tok = self.expect(T.STRING, "导入路径字符串")
        return ast.ImportDecl(path=path_tok.value, line=tok.line,
                              desc=path_tok.trailing)

    # ---------- world ----------
    def parse_world(self):
        line = self.advance().line
        name = self.expect_ident("世界名").value
        decl = ast.WorldDecl(name=name, line=line)
        self.expect(T.LBRACE)
        self.skip_newlines()
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("world 项")
            word = tok.value
            if word == "location":
                self.expect(T.EQUALS)
                loc = self.expect_ident("地点名")
                decl.locations.append(ast.Prop(name=loc.value, line=loc.line,
                                               desc=loc.trailing))
                self.end_of_stmt()
            elif word == "time":
                if "time" in seen:
                    raise NPLSyntaxError(tok.line, "world 内重复字段 time", code="NAR-012")
                seen.add("time")
                self.expect(T.EQUALS)
                decl.time = self.expect(T.TIMESTAMP, "时间戳").value
                self.end_of_stmt()
            elif word == "fact":
                fname = self.expect_ident("事实名")
                self.expect(T.EQUALS)
                val = self.peek()
                if val.type == T.BOOLEAN:
                    self.advance()
                    decl.facts.append(ast.FactItem(name=fname.value, value=val.value,
                                                   line=fname.line, desc=val.trailing,
                                                   vkind="bool"))
                elif val.type == T.NUMBER:
                    self.advance()
                    decl.facts.append(ast.FactItem(name=fname.value, value=float(val.value),
                                                   line=fname.line, desc=val.trailing,
                                                   vkind="num"))
                elif val.type == T.IDENT:
                    self.advance()   # v0.2 枚举值：自由标签（如 status = open）
                    decl.facts.append(ast.FactItem(name=fname.value, value=val.value,
                                                   line=fname.line, desc=val.trailing,
                                                   vkind="enum"))
                else:
                    raise NPLSyntaxError(val.line,
                                         f"fact 值必须是 true/false、数字或枚举标识符，得到 {self._describe(val)}",
                                         code="NAR-044")
                self.end_of_stmt()
            elif word == "entity":
                ename = self.expect_ident("实体名")
                self.expect(T.LBRACE)
                self.skip_newlines()
                ent = ast.EntityDecl(name=ename.value, line=ename.line)
                while not self.check(T.RBRACE):
                    a = self.expect_ident("属性名")
                    self.expect(T.EQUALS)
                    v = self.peek()
                    if v.type not in (T.IDENT, T.NUMBER, T.BOOLEAN, T.STRING):
                        raise NPLSyntaxError(v.line, f"实体属性值必须是标识符/数字/布尔/字符串，得到 {self._describe(v)}")
                    self.advance()
                    ent.attrs[a.value] = v.value
                    self.end_of_stmt()
                self.expect(T.RBRACE)
                self.end_of_stmt()
                decl.entities.append(ent)
            elif word == "process":
                # v0.4：多阶段世界进程（声明式知识；运行时事实由 sets/clears 驱动）
                pname = self.expect_ident("进程名")
                lbrace = self.expect(T.LBRACE)
                self.skip_newlines()
                proc = ast.ProcessDecl(name=pname.value, line=pname.line,
                                       desc=lbrace.trailing)
                seen_stages = set()
                while not self.check(T.RBRACE):
                    st = self.expect_ident("stage")
                    if st.value != "stage":
                        raise NPLSyntaxError(st.line,
                                             f"process 块内只支持 stage 声明，得到 '{st.value}'")
                    sname = self.expect_ident("阶段名")
                    if sname.value in seen_stages:
                        raise NPLSyntaxError(sname.line,
                                             f"进程 '{pname.value}' 内重复阶段 '{sname.value}'",
                                             code="NAR-012")
                    seen_stages.add(sname.value)
                    self.expect(T.LBRACE)
                    self.skip_newlines()
                    fact = None
                    sdesc = None
                    while not self.check(T.RBRACE):
                        f = self.expect_ident("阶段字段")
                        if f.value == "fact":
                            self.expect(T.EQUALS)
                            fid = self.expect_ident("事实 id")
                            fact = fid.value
                            sdesc = fid.trailing
                            self.end_of_stmt()
                        else:
                            raise NPLSyntaxError(f.line,
                                                 f"stage 块内未知字段 '{f.value}'（支持 fact）")
                        self.skip_newlines()
                    self.expect(T.RBRACE)
                    if fact is None:
                        raise NPLSyntaxError(sname.line,
                                             f"阶段 '{sname.value}' 缺少 fact 字段")
                    self.end_of_stmt()
                    proc.stages.append(ast.ProcessStage(
                        name=sname.value, fact=fact, line=sname.line, desc=sdesc))
                    self.skip_newlines()
                self.expect(T.RBRACE)
                self.end_of_stmt()
                decl.processes.append(proc)
            else:
                raise NPLSyntaxError(tok.line, f"world 块内未知项 '{word}'（支持 {WORLD_WORDS}）")
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return decl

    # ---------- character ----------
    def parse_character(self):
        line = self.advance().line
        name = self.expect_ident("人物名").value
        decl = ast.CharacterDecl(name=name, line=line)
        lbrace = self.expect(T.LBRACE)
        decl.desc = lbrace.trailing
        self.skip_newlines()
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("人物小节")
            word = tok.value
            if word in SECTION_WORDS:
                if word in seen:
                    raise NPLSyntaxError(tok.line, f"character 内重复小节 '{word}'", code="NAR-012")
                seen.add(word)
                self.expect(T.COLON)
                if word == "suspects":
                    getattr(decl, word).extend(self.parse_suspect_items())
                else:
                    items = self.parse_item_list()
                    getattr(decl, word).extend(items)
            elif word in TRAIT_WORDS:
                if word in seen:
                    raise NPLSyntaxError(tok.line, f"character 内重复小节 '{word}'", code="NAR-012")
                seen.add(word)
                self.expect(T.COLON)
                getattr(decl, word).extend(self.parse_trait_list())
            elif word == RELATION_WORD:
                if word in seen:
                    raise NPLSyntaxError(tok.line, f"character 内重复小节 '{word}'", code="NAR-012")
                seen.add(word)
                self.expect(T.COLON)
                decl.relations.extend(self.parse_relation_items())
            else:
                raise NPLSyntaxError(tok.line,
                                     f"character 块内未知小节 '{word}'（支持 knows/believes/suspects/does_not_know/intends/goal/personality/emotion/relations）")
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return decl

    def parse_item_list(self):
        """认知/意图小节条目：同行 `knows: a, b` 或逐行形式；支持嵌套 `B.knows(x)`。"""
        items = []
        if self.check(T.IDENT):
            items.append(self.parse_epistemic_entry())
            while self.accept(T.COMMA):
                items.append(self.parse_epistemic_entry())
            self.end_of_stmt()
            return items
        if self.check(T.RBRACE) or self.check(T.EOF):
            return items
        self.expect(T.NEWLINE)
        self.skip_newlines()
        # 逐行形式：每行一个（或逗号分隔的多个）命题；IDENT 后跟 ':' 说明是下一个小节头
        while self.check(T.IDENT) and self.peek(1).type != T.COLON:
            items.append(self.parse_epistemic_entry())
            while self.accept(T.COMMA):
                items.append(self.parse_epistemic_entry())
            self.end_of_stmt()
            self.skip_newlines()
        return items

    def parse_epistemic_entry(self, depth=0):
        """一条认知条目：普通命题 `x`，或嵌套心智 `B.knows(x)`（M3 一层 / v0.2 递归多层）。"""
        tok = self.expect_ident()
        if self.check(T.DOT):
            self.advance()
            verb = self.expect_ident("心智动词（knows/does_not_know/believes）")
            if verb.value not in NEST_VERBS:
                raise NPLSyntaxError(verb.line,
                                     f"非法心智动词 '{verb.value}'（支持 knows/does_not_know/believes）")
            self.expect(T.LPAREN)
            inner = self.parse_epistemic_entry(depth + 1)
            self.expect(T.RPAREN)
            if isinstance(inner, ast.NestedBelief):
                return ast.NestedBelief(path=[(tok.value, verb.value)] + inner.path,
                                        prop=inner.prop, line=tok.line, desc=inner.desc)
            return ast.NestedBelief(path=[(tok.value, verb.value)], prop=inner.name,
                                    line=tok.line, desc=inner.desc)
        if depth > 0:
            return ast.Prop(name=tok.value, line=tok.line)
        return ast.Prop(name=tok.value, line=tok.line)

    def parse_suspect_items(self):
        """suspects 小节条目：`x`（默认置信度 0.5）或 `x (0.7)`。"""
        items = []

        def one():
            t = self.expect_ident("怀疑对象")
            conf = 0.5
            if self.accept(T.LPAREN):
                num = self.expect(T.NUMBER, "置信度(0~1)")
                conf = float(num.value)
                self.expect(T.RPAREN)
            return ast.Suspect(name=t.value, confidence=conf, line=t.line)

        if self.check(T.IDENT):
            items.append(one())
            while self.accept(T.COMMA):
                items.append(one())
            self.end_of_stmt()
            return items
        if self.check(T.RBRACE) or self.check(T.EOF):
            return items
        self.expect(T.NEWLINE)
        self.skip_newlines()
        while self.check(T.IDENT) and self.peek(1).type != T.COLON:
            items.append(one())
            while self.accept(T.COMMA):
                items.append(one())
            self.end_of_stmt()
            self.skip_newlines()
        return items

    def parse_relation_items(self):
        """v0.5 relations 小节条目：`目标 : 态度 = 数值`（行尾注释=理由）。"""
        items = []

        def one():
            target = self.expect_ident("关系目标人物")
            self.expect(T.COLON)
            attitude = self.expect_ident("态度名")
            self.expect(T.EQUALS)
            num = self.expect(T.NUMBER, "态度值(-1.0~1.0)")
            return ast.Relation(target=target.value, attitude=attitude.value,
                                value=float(num.value), line=target.line,
                                reason=num.trailing)

        if self.check(T.IDENT):
            items.append(one())
            self.end_of_stmt()
            return items
        if self.check(T.RBRACE) or self.check(T.EOF):
            return items
        self.expect(T.NEWLINE)
        self.skip_newlines()
        # 下一个 IDENT 是已知小节关键字（含 relations 与特质节）时停止，交给上层分发产生 NAR-012
        while (self.check(T.IDENT) and self.peek(1).type == T.COLON
               and self.peek().value not in SECTION_WORDS
               and self.peek().value != RELATION_WORD):
            items.append(one())
            self.end_of_stmt()
            self.skip_newlines()
        return items

    def parse_relation_changes(self):
        """v0.5 relation_changes 场景块：`主体 -> 目标 : 态度 = 数值`（行尾注释=理由）。"""
        self.expect(T.LBRACE)
        self.skip_newlines()
        changes = []

        def one():
            subject = self.expect_ident("关系变更主体")
            self.expect(T.ARROW)
            target = self.expect_ident("关系变更目标")
            self.expect(T.COLON)
            attitude = self.expect_ident("态度名")
            self.expect(T.EQUALS)
            num = self.expect(T.NUMBER, "态度值(-1.0~1.0)")
            return ast.RelationChange(subject=subject.value, target=target.value,
                                      attitude=attitude.value, value=float(num.value),
                                      line=subject.line, reason=num.trailing)

        while not self.check(T.RBRACE):
            changes.append(one())
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return changes

    def parse_trait_list(self):
        """personality/emotion 条目：`名称 = 数值`。"""
        traits = []

        def one():
            name = self.expect_ident("特质名")
            self.expect(T.EQUALS)
            num = self.expect(T.NUMBER, "强度(0~1)")
            return ast.Trait(name=name.value, value=float(num.value), line=name.line)

        if self.check(T.IDENT) and self.peek(1).type == T.EQUALS:
            traits.append(one())
            self.end_of_stmt()
            return traits
        if self.check(T.RBRACE) or self.check(T.EOF):
            return traits
        self.expect(T.NEWLINE)
        self.skip_newlines()
        while self.check(T.IDENT) and self.peek(1).type == T.EQUALS:
            traits.append(one())
            self.end_of_stmt()
            self.skip_newlines()
        return traits

    # ---------- information ----------
    def parse_information(self):
        line = self.advance().line
        name = self.expect_ident("信息对象名").value
        decl = ast.InformationDecl(name=name, line=line)
        lbrace = self.expect(T.LBRACE)
        decl.desc = lbrace.trailing
        self.skip_newlines()
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("information 字段")
            word = tok.value
            if word not in ("truth", "known_by", "unknown_to", "suspected_by", "public"):
                raise NPLSyntaxError(tok.line, f"information 块内未知字段 '{word}'（支持 {INFO_WORDS}）")
            if word in seen:
                raise NPLSyntaxError(tok.line, f"information 内重复字段 '{word}'", code="NAR-012")
            seen.add(word)
            self.expect(T.EQUALS)
            if word == "truth":
                t = self.expect_ident("事实 id")
                decl.truth = t.value
                decl.truth_line = t.line
            elif word in ("known_by", "unknown_to"):
                getattr(decl, word).extend(self.parse_id_list())
            elif word == "suspected_by":
                decl.suspected_by.extend(self.parse_suspect_list())
            else:
                decl.public = self.expect(T.BOOLEAN, "true/false").value
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return decl

    def parse_id_list(self):
        items = []
        self.expect(T.LBRACKET)
        if not self.check(T.RBRACKET):
            t = self.expect_ident()
            items.append(ast.Prop(name=t.value, line=t.line))
            while self.accept(T.COMMA):
                t = self.expect_ident()
                items.append(ast.Prop(name=t.value, line=t.line))
        self.expect(T.RBRACKET)
        return items

    def parse_suspect_list(self):
        items = []
        self.expect(T.LBRACKET)
        if not self.check(T.RBRACKET):
            while True:
                t = self.expect_ident("人物名")
                self.expect(T.EQUALS)
                num = self.expect(T.NUMBER, "置信度(0~1)")
                items.append(ast.Suspect(name=t.value, confidence=float(num.value), line=t.line))
                if not self.accept(T.COMMA):
                    break
        self.expect(T.RBRACKET)
        return items

    # ---------- scene ----------
    def parse_scene(self):
        line = self.advance().line
        title = self.expect(T.STRING, "场景标题（字符串）").value
        decl = ast.SceneDecl(title=title, line=line)
        self.expect(T.LBRACE)
        self.skip_newlines()
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("场景项")
            word = tok.value
            if word not in ("pov", "location", "world_time", "flashback", "participants",
                            "access", "events", "information_changes", "dramatic_goal",
                            "emotional_arc", "motifs", "foreshadows", "withholds",
                            "misdirects", "relation_changes"):
                raise NPLSyntaxError(tok.line, f"scene 块内未知项 '{word}'（支持 {SCENE_WORDS}）")
            if word in seen:
                raise NPLSyntaxError(tok.line, f"scene 内重复项 '{word}'", code="NAR-012")
            seen.add(word)
            if word == "pov":
                self.expect(T.EQUALS)
                p = self.expect_ident("POV 人物")
                decl.pov = p.value
                decl.pov_line = p.line
                self.end_of_stmt()
            elif word == "flashback":
                self.expect(T.EQUALS)
                decl.flashback = self.expect(T.BOOLEAN, "true/false").value
                self.end_of_stmt()
            elif word == "location":
                self.expect(T.EQUALS)
                decl.location = self.expect_ident("地点").value
                self.end_of_stmt()
            elif word == "world_time":
                self.expect(T.EQUALS)
                decl.world_time = self.expect(T.TIMESTAMP, "时间戳").value
                self.end_of_stmt()
            elif word == "participants":
                self.expect(T.EQUALS)
                decl.participants = self.parse_id_list()
                self.end_of_stmt()
            elif word == "access":
                self.parse_access_block(decl)
            elif word in ("events", "information_changes"):
                self.parse_event_block(decl, word)
            elif word == "dramatic_goal":
                self.parse_goal_block(decl)
            elif word == "motifs":
                self.parse_motif_block(decl)
            elif word == "foreshadows":
                self.parse_literary_block(decl, "foreshadows")
            elif word == "withholds":
                self.parse_withhold_block(decl)
            elif word == "misdirects":
                self.parse_literary_block(decl, "misdirects")
            elif word == "relation_changes":
                decl.relation_changes.extend(self.parse_relation_changes())
            else:
                self.parse_arc_block(decl)
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return decl

    def parse_access_block(self, scene):
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            tok = self.expect_ident()
            kind = tok.value
            if kind not in ("allow", "deny"):
                raise NPLSyntaxError(tok.line, f"access 规则必须是 allow/deny，得到 '{kind}'")
            self.expect(T.EQUALS)
            subject = self.expect_ident("主体（人物或 world）")
            self.expect(T.DOT)
            cap = self.expect_ident("能力名")
            scene.access.append(ast.AccessRule(kind=kind, subject=subject.value,
                                               capability=cap.value, line=tok.line,
                                               desc=cap.trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    def parse_event_block(self, scene, which):
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            actor = self.expect_ident("事件主体")
            self.expect(T.DOT)
            action = self.expect_ident("动作")
            args = []
            if self.accept(T.LPAREN):
                if not self.check(T.RPAREN):
                    args.append(self.parse_event_arg())
                    while self.accept(T.COMMA):
                        args.append(self.parse_event_arg())
                self.expect(T.RPAREN)
            desc = self.toks[self.i - 1].trailing  # 行尾注释 = 语义描述
            getattr(scene, which).append(
                ast.EventRef(actor=actor.value, action=action.value, args=args,
                             line=actor.line, desc=desc))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    def parse_event_arg(self):
        """事件参数：普通 id 或嵌套心智 `B.knows(x)`（序列化为 "B.knows(x)" 字符串）。"""
        t = self.expect_ident()
        if self.check(T.DOT):
            self.advance()
            verb = self.expect_ident("心智动词（knows/does_not_know/believes）")
            self.expect(T.LPAREN)
            prop = self.expect_ident("命题 id")
            self.expect(T.RPAREN)
            return f"{t.value}.{verb.value}({prop.value})"
        return t.value

    def parse_goal_block(self, scene):
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            tok = self.expect_ident()
            kind = tok.value
            if kind not in ("reveal", "conceal"):
                raise NPLSyntaxError(tok.line, f"dramatic_goal 项必须是 reveal/conceal，得到 '{kind}'")
            self.expect(T.EQUALS)
            target = self.expect_ident("信息对象或事实 id")
            scene.dramatic_goal.append(ast.GoalItem(kind=kind, target=target.value,
                                                    line=tok.line,
                                                    desc=target.trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    def parse_arc_block(self, scene):
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            who = self.expect_ident("人物名")
            self.expect(T.COLON)
            states = [self.expect_ident("情绪状态")]
            while self.accept(T.ARROW):
                states.append(self.expect_ident("情绪状态"))
            scene.emotional_arc.append(ast.ArcEntry(
                character=who.value, states=[s.value for s in states],
                line=who.line, desc=states[-1].trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    # ---------- M4 文学原语 ----------
    def parse_motif_block(self, scene):
        """motifs { 雨 = introduce  // desc }"""
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            name = self.expect_ident("母题 id")
            self.expect(T.EQUALS)
            role = self.expect_ident(f"母题角色（{'/'.join(MOTIF_ROLES)}）")
            if role.value not in MOTIF_ROLES:
                raise NPLSyntaxError(role.line,
                                     f"母题角色必须是 {'/'.join(MOTIF_ROLES)}，得到 '{role.value}'")
            scene.motifs.append(ast.MotifRef(motif=name.value, role=role.value,
                                             line=name.line, desc=role.trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    def parse_literary_block(self, scene, which):
        """foreshadows / misdirects { id  // desc }（逐行，desc 可选）"""
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            t = self.expect_ident("事实或信息对象 id")
            getattr(scene, which).append(
                ast.LiteraryRef(target=t.value, line=t.line, desc=t.trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    def parse_withhold_block(self, scene):
        """withholds { id until = N  // desc }（N = 释放幕次，1 起）"""
        self.expect(T.LBRACE)
        self.skip_newlines()
        while not self.check(T.RBRACE):
            t = self.expect_ident("事实或信息对象 id")
            word = self.expect_ident("withhold 字段（until）")
            if word.value != "until":
                raise NPLSyntaxError(word.line, f"withholds 内未知字段 '{word.value}'（支持 until）")
            self.expect(T.EQUALS)
            num = self.expect(T.NUMBER, "释放幕次（整数）")
            until = int(float(num.value))
            if until != float(num.value):
                raise NPLSyntaxError(num.line, "until 必须是整数幕次")
            scene.withholds.append(ast.WithholdRef(
                target=t.value, until=until, line=t.line, desc=num.trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()

    # ---------- M4 style ----------
    def parse_style_decl(self):
        line = self.advance().line
        key = self.expect_ident("风格名").value
        decl = ast.StyleDecl(key=key, line=line)
        lbrace = self.expect(T.LBRACE)
        decl.desc = lbrace.trailing
        self.skip_newlines()
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("风格字段")
            word = tok.value
            if word not in STYLE_FIELDS:
                raise NPLSyntaxError(tok.line,
                                     f"style 块内未知字段 '{word}'（支持 {'/'.join(STYLE_FIELDS)}）")
            if word != "rule" and word in seen:
                raise NPLSyntaxError(tok.line, f"style 内重复字段 '{word}'", code="NAR-012")
            seen.add(word)
            self.expect(T.EQUALS)
            if word == "sentence_max":
                decl.sentence_max = float(self.expect(T.NUMBER, "句长上限（字数）").value)
            elif word == "emotion_naming":
                v = self.expect_ident("forbid/allow")
                if v.value not in ("forbid", "allow"):
                    raise NPLSyntaxError(v.line, f"emotion_naming 必须是 forbid/allow，得到 '{v.value}'")
                decl.emotion_naming = v.value
            elif word == "sensory":
                v = self.expect_ident("low/mid/high")
                if v.value not in ("low", "mid", "high"):
                    raise NPLSyntaxError(v.line, f"sensory 必须是 low/mid/high，得到 '{v.value}'")
                decl.sensory = v.value
            elif word == "dialogue_gaps":
                decl.dialogue_gaps = self.expect(T.BOOLEAN, "true/false").value
            elif word == "desc":
                decl.desc = self.expect(T.STRING, "风格描述").value
            else:  # rule（可重复）
                decl.rules.append(self.expect(T.STRING, "规则文本").value)
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return decl

    # ---------- intent（v0.5 章节意图） ----------
    def parse_intent_block(self):
        """intent 块：`goal = fact` / `forbid = fact` / `pacing = suspicion_up (fact)`。

        行尾注释为语义说明；同一 (kind, pacing_kind, arg) 重复 → NAR-012。
        """
        self.advance()          # 'intent'
        self.expect(T.LBRACE)
        self.skip_newlines()
        lines = []
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("意图类型")
            kind = tok.value
            if kind not in INTENT_KINDS:
                raise NPLSyntaxError(tok.line,
                                     f"未知意图类型 '{kind}'（支持 goal/forbid/pacing）",
                                     code="NAR-001")
            self.expect(T.EQUALS)
            pacing_kind = None
            if kind == "pacing":
                pk = self.expect_ident("节奏类型")
                if pk.value not in PACING_KINDS:
                    raise NPLSyntaxError(pk.line,
                                         f"未知节奏类型 '{pk.value}'（支持 suspicion_up）",
                                         code="NAR-001")
                pacing_kind = pk.value
                self.expect(T.LPAREN)
            arg = self.expect_ident("意图目标")
            if kind == "pacing":
                self.expect(T.RPAREN)
            key = (kind, pacing_kind, arg.value)
            if key in seen:
                raise NPLSyntaxError(arg.line, f"重复的意图声明 '{kind} {arg.value}'", code="NAR-012")
            seen.add(key)
            lines.append(ast.IntentLine(kind=kind, arg=arg.value, pacing_kind=pacing_kind,
                                        line=tok.line, desc=arg.trailing))
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return lines

    # ---------- render ----------
    def parse_render(self):
        line = self.advance().line
        decl = ast.RenderDecl(line=line)
        self.expect(T.LBRACE)
        self.skip_newlines()
        seen = set()
        while not self.check(T.RBRACE):
            tok = self.expect_ident("渲染配置项")
            word = tok.value
            if word not in ("style", "language"):
                raise NPLSyntaxError(tok.line, f"render 块内未知项 '{word}'（支持 style/language）")
            if word in seen:
                raise NPLSyntaxError(tok.line, f"render 内重复项 '{word}'", code="NAR-012")
            seen.add(word)
            self.expect(T.EQUALS)
            setattr(decl, word, self.expect_ident().value)
            self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE)
        self.end_of_stmt()
        return decl


def parse_source(source: str) -> ast.Program:
    """入口：源码文本 → Program AST。语法错误抛 NPLSyntaxError。"""
    return Parser(tokenize(source)).parse_program()


# ---------- v0.2 多文件加载 ----------

def load_program(entry_path, _chain=None):
    """入口文件 → 递归跟随 import → 合并 Program。

    - 相对路径按所在文件解析；已合并的文件跳过（import 语义 = 单次包含）。
    - 循环导入 NAR-016；文件不存在 NAR-015；跨文件重复顶层声明 NAR-011。
    """
    from pathlib import Path
    entry = Path(entry_path).resolve()
    if _chain is None:
        _chain = []
    if entry in _chain:
        cycle = " -> ".join(str(p.name) for p in _chain + [entry])
        raise NPLSyntaxError(0, f"import 循环：{cycle}", code="NAR-016")
    if not entry.is_file():
        what = "import 的文件" if _chain else "文件"
        raise NPLSyntaxError(0, f"{what}不存在：{entry}", code="NAR-015")
    text = entry.read_text(encoding="utf-8-sig")
    program = parse_source(text)
    program.source_files.append(str(entry))

    # 场景顺序 = 导入文件（按 import 序）在前，入口自身场景在后（叙事顺序语义）
    entry_scenes = program.scenes
    entry_scene_titles = {s.title for s in entry_scenes}
    program.scenes = []

    merged = program
    base = entry.parent
    for imp in program.imports:
        target = (base / imp.path).resolve()
        sub = load_program(target, _chain + [entry])
        _merge_program(merged, sub, imp, entry, entry_scene_titles)
    program.scenes.extend(entry_scenes)
    return merged


def _merge_program(dst: "ast.Program", src: "ast.Program", imp, entry,
                   entry_scene_titles=None):
    """把 src（被导入文件）合并进 dst。src.imports 已在其自身 load 中展开。"""
    entry_scene_titles = entry_scene_titles or set()

    def dup(msg):
        raise NPLSyntaxError(imp.line, msg, code="NAR-011")

    if src.world is not None:
        if dst.world is not None:
            dup(f"跨文件重复 world 声明：{entry.name} 与导入文件均定义 world")
        dst.world = src.world
    by_name = {("character", c.name): c for c in dst.characters}
    for c in src.characters:
        if ("character", c.name) in by_name:
            dup(f"跨文件重复人物声明 '{c.name}'")
        dst.characters.append(c)
    by_name = {("info", i.name): i for i in dst.informations}
    for i in src.informations:
        if ("info", i.name) in by_name:
            dup(f"跨文件重复信息对象声明 '{i.name}'")
        dst.informations.append(i)
    by_title = {s.title: s for s in dst.scenes}
    for s in src.scenes:
        if s.title in by_title or s.title in entry_scene_titles:
            dup(f"跨文件重复场景标题 '{s.title}'")
        dst.scenes.append(s)
    by_key = {st.key: st for st in dst.styles}
    for st in src.styles:
        if st.key in by_key:
            dup(f"跨文件重复风格声明 '{st.key}'")
        dst.styles.append(st)
    if src.render is not None:
        if dst.render is None:
            dst.render = src.render
    dst.source_files.extend(src.source_files)
