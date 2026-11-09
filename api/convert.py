"""
Back-end do conversor .ui -> .py (PyQt6), feito com Flask.

Endpoint: POST /api/convert
  - corpo da requisição: o conteúdo bruto do arquivo .ui
  - cabeçalho X-Filename: nome original do arquivo (codificado com encodeURIComponent)

Respostas:
  - 200: o arquivo .py gerado (Content-Disposition: attachment)
  - 4xx/5xx: JSON {"error": "mensagem"}

Rodar localmente (serve também o site da pasta public/):
  python api/convert.py     ->  http://127.0.0.1:5000
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from flask import Flask, Response, jsonify, request, send_from_directory

MAX_BYTES = 1_000_000  # 1 MB — arquivos .ui reais costumam ter poucos KB
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public")

# static_folder só é usado ao rodar localmente; na Vercel a pasta public/ é servida pela CDN
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES


def compile_ui(ui_bytes: bytes, nome_ui: str = "formulario.ui") -> str:
    """Converte o conteúdo de um .ui em código Python (PyQt6) sem precisar do PyQt6 instalado.

    executable=True acrescenta o bloco final (if __name__ == "__main__") que abre a janela.
    """
    return converter_ui(ui_bytes, filename=nome_ui, executable=True).code


def safe_basename(raw_name: str) -> str:
    """Gera um nome de arquivo seguro (sem caminho, sem caracteres estranhos)."""
    nome = unquote(raw_name or "").replace("\\", "/").split("/")[-1]
    nome = re.sub(r"\.ui$", "", nome, flags=re.IGNORECASE)
    nome = re.sub(r"[^A-Za-z0-9_-]", "_", nome).strip("_")
    return nome or "form"


def erro(status: int, mensagem: str):
    resposta = jsonify({"error": mensagem})
    resposta.status_code = status
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.errorhandler(413)
def arquivo_grande(_):
    return erro(413, "Arquivo muito grande (limite de 1 MB).")


@app.errorhandler(405)
def metodo_invalido(_):
    return erro(405, "Use o método POST para enviar um arquivo .ui.")


@app.post("/api/convert")
def convert():
    conteudo = request.get_data()  # corpo bruto; respeita MAX_CONTENT_LENGTH

    if not conteudo:
        return erro(400, "Nenhum arquivo foi enviado.")

    # por segurança, .ui reais nunca têm DOCTYPE/ENTITY
    if b"<!doctype" in conteudo.lower() or b"<!entity" in conteudo.lower():
        return erro(400, "Arquivos .ui com DOCTYPE/ENTITY não são aceitos.")

    # validação: precisa ser um XML com raiz <ui>
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return erro(400, "O arquivo não é um XML válido. Exporte-o novamente pelo Qt Designer.")
    if raiz.tag != "ui":
        return erro(400, "Esse arquivo não parece um .ui do Qt Designer (raiz <ui> não encontrada).")

    # conversão
    try:
        nome_ui = safe_basename(request.headers.get("X-Filename", "")) + ".ui"
        codigo = compile_ui(conteudo, nome_ui)
    except ConversionError as e:
        return erro(422, str(e))
    except Exception as e:  # erros do uic (widget desconhecido, propriedade inválida etc.)
        return erro(422, f"Não foi possível converter esse .ui: {e}")

    # devolve o .py para download
    nome = safe_basename(request.headers.get("X-Filename", "")) + ".py"
    return Response(
        codigo,
        mimetype="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="{nome}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/convert")
def convert_get():
    return erro(405, "Use o método POST para enviar um arquivo .ui.")


@app.get("/")
def index():
    """Só para o uso local: na Vercel o index.html é servido direto da pasta public/."""
    return send_from_directory(PUBLIC_DIR, "index.html")


# =========================================================================== #
#  MOTOR DE CONVERSÃO .ui -> PyQt6 (Python puro, sem depender do PyQt6/Qt)
#  Gera uma classe Ui_<Nome> no mesmo formato do pyuic6.
#  Função de entrada: converter_ui(conteudo, filename, executable)
# =========================================================================== #

class ConversionError(Exception):
    """Erro de entrada inválida (XML malformado, não é um .ui, etc.)."""


class Result:
    """Resultado da conversão (classe simples, sem dataclass, para rodar em qualquer carregador)."""

    def __init__(self, code, class_name, base_class, widgets, warnings=None):
        self.code = code
        self.class_name = class_name
        self.base_class = base_class
        self.widgets = widgets
        self.warnings = warnings if warnings is not None else []


_QTGUI = set(
    "QAction QActionGroup QBrush QColor QCursor QFont QIcon QPalette QPixmap QKeySequence "
    "QImage QIntValidator QDoubleValidator QRegularExpressionValidator QValidator "
    "QStandardItemModel QShortcut QTextCursor QTextDocument QMovie QPainter QPen".split()
)
_QTCORE = set(
    "Qt QRect QRectF QSize QSizeF QPoint QPointF QDate QTime QDateTime QUrl QLocale QObject "
    "QTimer QCoreApplication QMetaObject QStringListModel QSortFilterProxyModel "
    "QAbstractItemModel".split()
)
_EXTRA = {
    "QSvgWidget": "QtSvgWidgets",
    "QWebEngineView": "QtWebEngineWidgets",
    "QVideoWidget": "QtMultimediaWidgets",
    "QOpenGLWidget": "QtOpenGLWidgets",
    "QQuickWidget": "QtQuickWidgets",
}


def _module_of(cls: str) -> str:
    if cls in _EXTRA:
        return _EXTRA[cls]
    if cls in _QTGUI:
        return "QtGui"
    if cls in _QTCORE:
        return "QtCore"
    return "QtWidgets"


_ENUMS = {
    "Qt": {
        "AlignmentFlag": "AlignLeft AlignLeading AlignRight AlignTrailing AlignHCenter AlignJustify "
                         "AlignAbsolute AlignTop AlignBottom AlignVCenter AlignBaseline AlignCenter",
        "Orientation": "Horizontal Vertical",
        "CursorShape": "ArrowCursor UpArrowCursor CrossCursor WaitCursor IBeamCursor SizeVerCursor "
                       "SizeHorCursor SizeBDiagCursor SizeFDiagCursor SizeAllCursor BlankCursor "
                       "SplitVCursor SplitHCursor PointingHandCursor ForbiddenCursor WhatsThisCursor "
                       "BusyCursor OpenHandCursor ClosedHandCursor DragCopyCursor DragMoveCursor "
                       "DragLinkCursor",
        "ScrollBarPolicy": "ScrollBarAsNeeded ScrollBarAlwaysOff ScrollBarAlwaysOn",
        "FocusPolicy": "NoFocus TabFocus ClickFocus StrongFocus WheelFocus",
        "ContextMenuPolicy": "NoContextMenu DefaultContextMenu ActionsContextMenu CustomContextMenu "
                             "PreventContextMenu",
        "LayoutDirection": "LeftToRight RightToLeft LayoutDirectionAuto",
        "TextFormat": "PlainText RichText AutoText MarkdownText",
        "ToolButtonStyle": "ToolButtonIconOnly ToolButtonTextOnly ToolButtonTextBesideIcon "
                           "ToolButtonTextUnderIcon ToolButtonFollowStyle",
        "WindowModality": "NonModal WindowModal ApplicationModal",
        "TextElideMode": "ElideLeft ElideRight ElideMiddle ElideNone",
        "CheckState": "Unchecked PartiallyChecked Checked",
        "ToolBarArea": "LeftToolBarArea RightToolBarArea TopToolBarArea BottomToolBarArea "
                       "AllToolBarAreas NoToolBarArea",
        "DockWidgetArea": "LeftDockWidgetArea RightDockWidgetArea TopDockWidgetArea "
                          "BottomDockWidgetArea AllDockWidgetAreas NoDockWidgetArea",
        "BrushStyle": "NoBrush SolidPattern Dense1Pattern Dense2Pattern Dense3Pattern Dense4Pattern "
                      "Dense5Pattern Dense6Pattern Dense7Pattern HorPattern VerPattern CrossPattern "
                      "BDiagPattern FDiagPattern DiagCrossPattern",
        "TextInteractionFlag": "NoTextInteraction TextSelectableByMouse TextSelectableByKeyboard "
                               "LinksAccessibleByMouse LinksAccessibleByKeyboard TextEditable "
                               "TextEditorInteraction TextBrowserInteraction",
        "WindowType": "Widget Window Dialog Sheet Drawer Popup Tool ToolTip SplashScreen Desktop "
                      "SubWindow WindowTitleHint WindowSystemMenuHint WindowMinimizeButtonHint "
                      "WindowMaximizeButtonHint WindowMinMaxButtonsHint WindowCloseButtonHint "
                      "WindowContextHelpButtonHint WindowStaysOnTopHint WindowStaysOnBottomHint "
                      "FramelessWindowHint CustomizeWindowHint",
        "ArrowType": "NoArrow UpArrow DownArrow LeftArrow RightArrow",
        "SortOrder": "AscendingOrder DescendingOrder",
        "ItemFlag": "NoItemFlags ItemIsSelectable ItemIsEditable ItemIsDragEnabled ItemIsDropEnabled "
                    "ItemIsUserCheckable ItemIsEnabled ItemIsAutoTristate ItemNeverHasChildren "
                    "ItemIsUserTristate",
    },
    "QFrame": {"Shape": "NoFrame Box Panel WinPanel HLine VLine StyledPanel",
               "Shadow": "Plain Raised Sunken"},
    "QSizePolicy": {"Policy": "Fixed Minimum Maximum Preferred MinimumExpanding Expanding Ignored"},
    "QAbstractItemView": {
        "SelectionMode": "NoSelection SingleSelection MultiSelection ExtendedSelection ContiguousSelection",
        "SelectionBehavior": "SelectItems SelectRows SelectColumns",
        "EditTrigger": "NoEditTriggers CurrentChanged DoubleClicked SelectedClicked EditKeyPressed "
                       "AnyKeyPressed AllEditTriggers",
        "ScrollMode": "ScrollPerItem ScrollPerPixel",
        "DragDropMode": "NoDragDrop DragOnly DropOnly DragDrop InternalMove",
    },
    "QLineEdit": {"EchoMode": "Normal NoEcho Password PasswordEchoOnEdit"},
    "QSlider": {"TickPosition": "NoTicks TicksBothSides TicksAbove TicksLeft TicksBelow TicksRight"},
    "QTabWidget": {"TabPosition": "North South West East", "TabShape": "Rounded Triangular"},
    "QDialogButtonBox": {
        "StandardButton": "NoButton Ok Save SaveAll Open Yes YesToAll No NoToAll Abort Retry Ignore "
                          "Close Cancel Discard Help Apply Reset RestoreDefaults"},
    "QComboBox": {
        "InsertPolicy": "NoInsert InsertAtTop InsertAtCurrent InsertAtBottom InsertAfterCurrent "
                        "InsertBeforeCurrent InsertAlphabetically",
        "SizeAdjustPolicy": "AdjustToContents AdjustToContentsOnFirstShow "
                            "AdjustToMinimumContentsLengthWithIcon"},
    "QAbstractSpinBox": {"ButtonSymbols": "UpDownArrows PlusMinus NoButtons",
                         "CorrectionMode": "CorrectToPreviousValue CorrectToNearestValue"},
    "QAbstractScrollArea": {
        "SizeAdjustPolicy": "AdjustIgnored AdjustToContents AdjustToContentsOnFirstShow"},
    "QListView": {"Flow": "LeftToRight TopToBottom", "ResizeMode": "Fixed Adjust",
                  "LayoutMode": "SinglePass Batched", "Movement": "Static Free Snap",
                  "ViewMode": "ListMode IconMode"},
    "QTextEdit": {"LineWrapMode": "NoWrap WidgetWidth FixedPixelWidth FixedColumnWidth",
                  "AutoFormattingFlag": "AutoNone AutoBulletList AutoAll"},
    "QPlainTextEdit": {"LineWrapMode": "NoWrap WidgetWidth"},
    "QToolButton": {"ToolButtonPopupMode": "DelayedPopup MenuButtonPopup InstantPopup"},
    "QLCDNumber": {"Mode": "Hex Dec Oct Bin", "SegmentStyle": "Outline Filled Flat"},
    "QLayout": {"SizeConstraint": "SetDefaultConstraint SetNoConstraint SetMinimumSize "
                                  "SetFixedSize SetMaximumSize SetMinAndMaxSize"},
    "QFormLayout": {
        "FieldGrowthPolicy": "FieldsStayAtSizeHint ExpandingFieldsGrow AllNonFixedFieldsGrow",
        "RowWrapPolicy": "DontWrapRows WrapLongRows WrapAllRows",
        "ItemRole": "LabelRole FieldRole SpanningRole"},
    "QProgressBar": {"Direction": "TopToBottom BottomToTop"},
    "QDateTimeEdit": {"Section": "NoSection AmPmSection MSecSection SecondSection MinuteSection "
                                 "HourSection DaySection MonthSection YearSection"},
    "QPalette": {"ColorGroup": "Active Disabled Inactive",
                 "ColorRole": "WindowText Button Light Midlight Dark Mid Text BrightText ButtonText "
                              "Base Window Shadow Highlight HighlightedText Link LinkVisited "
                              "AlternateBase NoRole ToolTipBase ToolTipText PlaceholderText"},
    "QIcon": {"Mode": "Normal Disabled Active Selected", "State": "On Off"},
    "QAction": {"MenuRole": "NoRole TextHeuristicRole ApplicationSpecificRole AboutQtRole AboutRole "
                            "PreferencesRole QuitRole"},
    "QFontComboBox": {"FontFilter": "AllFonts ScalableFonts NonScalableFonts MonospacedFonts "
                                    "ProportionalFonts"},
}

_ENUM_MAP = {}
for _cls, _groups in _ENUMS.items():
    for _enum, _vals in _groups.items():
        for _v in _vals.split():
            _ENUM_MAP[f"{_cls}::{_v}"] = f"{_module_of(_cls)}.{_cls}.{_enum}.{_v}"

_LAYOUT_MARGINS = ("leftMargin", "topMargin", "rightMargin", "bottomMargin")
_PAGE_PARENTS = {"QTabWidget", "QToolBox", "QStackedWidget", "QScrollArea"}
_DEFER_INDEX = {"QTabWidget", "QStackedWidget", "QToolBox", "QComboBox"}
_ICON_STATES = {
    "normaloff": ("Normal", "Off"), "normalon": ("Normal", "On"),
    "disabledoff": ("Disabled", "Off"), "disabledon": ("Disabled", "On"),
    "activeoff": ("Active", "Off"), "activeon": ("Active", "On"),
    "selectedoff": ("Selected", "Off"), "selectedon": ("Selected", "On"),
}
_HEADER_RE = re.compile(r"^(horizontalHeader|verticalHeader|header)([A-Z]\w*)$")


def _ident(name: str) -> str:
    n = re.sub(r"\W", "_", name or "")
    return "_" + n if not n or n[0].isdigit() else n


def _q(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r\n", "\n")
    s = s.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    return f'"{s}"'


def _setter(name: str) -> str:
    return "set" + name[0].upper() + name[1:]


def _txt(el, default: str = "") -> str:
    return (el.text or default).strip() if el is not None else default


class _Converter:
    def __init__(self, root, filename: str, executable: bool):
        self.root = root
        self.filename = filename
        self.executable = executable
        self.warnings = []
        self.setup = []      # corpo de setupUi
        self.retr = []       # corpo de retranslateUi
        self.deferred = []   # executado após criar widgets e ações
        self.groups = []
        self.custom = {}
        self.extra_modules = set()
        self.spacers = 0
        self.widgets = 0

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def qual(self, cls: str) -> str:
        if cls in self.custom:
            return cls
        if not cls.startswith("Q"):
            self.warn(f"Widget personalizado '{cls}' sem <customwidget>: ajuste o import no final do arquivo.")
            self.custom[cls] = cls.lower()
            return cls
        mod = _module_of(cls)
        if mod not in ("QtCore", "QtGui", "QtWidgets"):
            self.extra_modules.add(mod)
        return f"{mod}.{cls}"

    def enum(self, text: str) -> str:
        text = text.strip()
        if text in _ENUM_MAP:
            return _ENUM_MAP[text]
        if "::" in text:
            c, v = text.split("::", 1)
            self.warn(f"Enum não mapeado: {text} — confira no código gerado.")
            return f"{self.qual(c) if c != 'Qt' else 'QtCore.Qt'}.{v}"
        return text

    def flags(self, text: str) -> str:
        return "|".join(self.enum(t) for t in text.split("|") if t.strip())

    def tr(self, s) -> str:
        extra = f", {_q(s.get('comment'))}" if s.get("comment") else ""
        return f"_translate({_q(self.ctx)}, {_q(s.text or '')}{extra})"

    def ref(self, name: str) -> str:
        return self.root_name if name == self.top_raw else "self." + _ident(name)

    def color(self, c) -> str:
        r, g, b = (_txt(c.find(k), "0") for k in ("red", "green", "blue"))
        a = c.get("alpha")
        return f"QtGui.QColor({r}, {g}, {b}" + (f", {a})" if a not in (None, "255") else ")")

    def brush_lines(self, b) -> list:
        col = b.find("color")
        if col is None:
            self.warn("Pincel (brush) com textura/gradiente não é suportado e foi ignorado.")
            return []
        style = b.get("brushstyle", "SolidPattern")
        return [f"brush = QtGui.QBrush({self.color(col)})",
                f"brush.setStyle({self.enum('Qt::' + style)})"]

    def value(self, c, target: str):
        t, tx = c.tag, _txt(c)
        kids = lambda *names: ", ".join(_txt(c.find(n), "0") for n in names)  # noqa: E731
        if t == "bool":
            return [], "True" if tx == "true" else "False"
        if t in ("number", "longlong", "uint", "ulonglong", "double", "float"):
            return [], tx or "0"
        if t == "string":
            return [], _q(c.text or "")
        if t == "cstring":
            return [], _q(tx)
        if t == "enum":
            return [], self.enum(tx)
        if t == "set":
            return [], self.flags(tx)
        if t == "cursorShape":
            return [], f"QtGui.QCursor({self.enum('Qt::' + tx)})"
        if t in ("rect", "rectf"):
            return [], f"QtCore.QRect{'F' if t == 'rectf' else ''}({kids('x', 'y', 'width', 'height')})"
        if t in ("size", "sizef"):
            return [], f"QtCore.QSize{'F' if t == 'sizef' else ''}({kids('width', 'height')})"
        if t in ("point", "pointf"):
            return [], f"QtCore.QPoint{'F' if t == 'pointf' else ''}({kids('x', 'y')})"
        if t == "color":
            return [], self.color(c)
        if t == "stringlist":
            return [], "[" + ", ".join(_q(s.text or "") for s in c.findall("string")) + "]"
        if t == "date":
            return [], f"QtCore.QDate({kids('year', 'month', 'day')})"
        if t == "time":
            return [], f"QtCore.QTime({kids('hour', 'minute', 'second')})"
        if t == "datetime":
            return [], (f"QtCore.QDateTime(QtCore.QDate({kids('year', 'month', 'day')}), "
                        f"QtCore.QTime({kids('hour', 'minute', 'second')}))")
        if t == "url":
            return [], f"QtCore.QUrl({_q(_txt(c.find('string')))})"
        if t == "pixmap":
            return [], f"QtGui.QPixmap({_q(tx)})"
        if t == "font":
            pre = ["font = QtGui.QFont()"]
            for tag, fn in (("family", "setFamily"), ("pointsize", "setPointSize"),
                            ("pixelsize", "setPixelSize"), ("bold", "setBold"),
                            ("italic", "setItalic"), ("underline", "setUnderline"),
                            ("strikeout", "setStrikeOut"), ("kerning", "setKerning")):
                e = c.find(tag)
                if e is not None:
                    v = _q(_txt(e)) if tag == "family" else (
                        "True" if _txt(e) == "true" else "False" if _txt(e) == "false" else _txt(e))
                    pre.append(f"font.{fn}({v})")
            if c.find("stylestrategy") is not None:
                pre.append(f"font.setStyleStrategy(QtGui.QFont.StyleStrategy.{_txt(c.find('stylestrategy'))})")
            return pre, "font"
        if t == "sizepolicy":
            h, v = c.get("hsizetype", "Preferred"), c.get("vsizetype", "Preferred")
            return ([f"sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.{h}, "
                     f"QtWidgets.QSizePolicy.Policy.{v})",
                     f"sizePolicy.setHorizontalStretch({_txt(c.find('horstretch'), '0')})",
                     f"sizePolicy.setVerticalStretch({_txt(c.find('verstretch'), '0')})",
                     f"sizePolicy.setHeightForWidth({target}.sizePolicy().hasHeightForWidth())"],
                    "sizePolicy")
        if t == "iconset":
            if c.get("theme"):
                return [f"icon = QtGui.QIcon.fromTheme({_q(c.get('theme'))})"], "icon"
            pre = ["icon = QtGui.QIcon()"]
            for tag, (mode, state) in _ICON_STATES.items():
                e = c.find(tag)
                if e is not None and _txt(e):
                    pre.append(f"icon.addPixmap(QtGui.QPixmap({_q(_txt(e))}), "
                               f"QtGui.QIcon.Mode.{mode}, QtGui.QIcon.State.{state})")
            return pre, "icon"
        if t == "brush":
            return self.brush_lines(c) + [], "brush"
        if t == "palette":
            pre = ["palette = QtGui.QPalette()"]
            for grp in c:
                g = {"active": "Active", "inactive": "Inactive", "disabled": "Disabled"}.get(grp.tag)
                if not g:
                    continue
                for cr in grp.findall("colorrole"):
                    b = cr.find("brush")
                    lines = self.brush_lines(b) if b is not None else []
                    if lines:
                        pre += lines + [f"palette.setBrush(QtGui.QPalette.ColorGroup.{g}, "
                                        f"QtGui.QPalette.ColorRole.{cr.get('role')}, brush)"]
            return pre, "palette"
        self.warn(f"Tipo de propriedade não suportado: <{t}> (ignorado).")
        return [], "None"

    def do_prop(self, p, target: str, top: bool) -> None:
        name = p.get("name") or ""
        c = p[0] if len(p) else None
        if c is None or name == "objectName":
            return
        stdset = p.get("stdset") != "0"

        def stmt(expr: str) -> str:
            return (f"{target}.{_setter(name)}({expr})" if stdset
                    else f"{target}.setProperty({_q(name)}, {expr})")

        if name == "geometry" and c.tag == "rect":
            w, h = _txt(c.find("width"), "0"), _txt(c.find("height"), "0")
            if top:
                self.setup.append(f"{target}.resize({w}, {h})")
            else:
                pre, expr = self.value(c, target)
                self.setup.append(stmt(expr))
            return
        if name == "buddy":
            self.deferred.append(f"{target}.setBuddy({self.ref(_txt(c))})")
            return
        if c.tag == "string" and c.get("notr") != "true":
            self.retr.append(stmt(self.tr(c)))
            return
        pre, expr = self.value(c, target)
        if expr == "None":
            return
        self.setup += pre
        self.setup.append(stmt(expr))

    def props(self, el, target: str, cls: str, top: bool = False) -> list:
        deferred = []
        for p in el.findall("property"):
            if p.get("name") == "currentIndex" and cls in _DEFER_INDEX:
                deferred.append(p)
            else:
                self.do_prop(p, target, top)
        return deferred

    def attrs(self, el, ref: str, parent_ref, parent_cls) -> None:
        for a in el.findall("attribute"):
            name, c = a.get("name") or "", (a[0] if len(a) else None)
            if c is None:
                continue
            if parent_cls == "QTabWidget" and name in ("title", "toolTip", "whatsThis", "icon"):
                fn = {"title": "setTabText", "toolTip": "setTabToolTip", "whatsThis": "setTabWhatsThis",
                      "icon": "setTabIcon"}[name]
                if c.tag == "string":
                    self.retr.append(f"{parent_ref}.{fn}({parent_ref}.indexOf({ref}), {self.tr(c)})")
                else:
                    pre, expr = self.value(c, ref)
                    self.setup += pre
                    self.setup.append(f"{parent_ref}.{fn}({parent_ref}.indexOf({ref}), {expr})")
            elif parent_cls == "QToolBox" and name in ("label", "toolTip", "icon"):
                fn = {"label": "setItemText", "toolTip": "setItemToolTip", "icon": "setItemIcon"}[name]
                if c.tag == "string":
                    self.retr.append(f"{parent_ref}.{fn}({parent_ref}.indexOf({ref}), {self.tr(c)})")
                else:
                    pre, expr = self.value(c, ref)
                    self.setup += pre
                    self.setup.append(f"{parent_ref}.{fn}({parent_ref}.indexOf({ref}), {expr})")
            elif name == "buttonGroup":
                self.deferred.append(f"{self.ref(_txt(c))}.addButton({ref})")
            else:
                m = _HEADER_RE.match(name)
                if m:
                    acc = "header" if m.group(1) == "header" else m.group(1)
                    rest = m.group(2)
                    fn = "setSortIndicatorShown" if rest == "ShowSortIndicator" else "set" + rest
                    pre, expr = self.value(c, ref)
                    self.setup.append(f"{ref}.{acc}().{fn}({expr})")

    def item_props(self, it, var: str, retr_path: str, with_col: bool = False) -> None:
        lines = []
        for p in it.findall("property"):
            name, c = p.get("name") or "", (p[0] if len(p) else None)
            if c is None:
                continue
            col = f"{p.get('column') or 0}, " if with_col else ""
            if c.tag == "string" and c.get("notr") != "true":
                lines.append(f"{var}.{_setter(name)}({col}{self.tr(c)})")
            else:
                pre, expr = self.value(c, var)
                self.setup += pre
                self.setup.append(f"{var}.{_setter(name)}({col}{expr})")
        if lines:
            self.retr.append(f"{var} = {retr_path}")
            self.retr += lines

    def tree_items(self, el, parent_expr: str, parent_path: str, depth: int) -> None:
        for i, it in enumerate(el.findall("item")):
            var = f"item_{depth}"
            self.setup.append(f"{var} = QtWidgets.QTreeWidgetItem({parent_expr})")
            path = f"{parent_path}.topLevelItem({i})" if depth == 0 else f"{parent_path}.child({i})"
            self.item_props(it, var, path, with_col=True)
            self.tree_items(it, var, path, depth + 1)

    def items(self, el, ref: str, cls: str) -> None:
        if cls == "QComboBox":
            for i, it in enumerate(el.findall("item")):
                self.setup.append(f'{ref}.addItem("")')
                for p in it.findall("property"):
                    c = p[0] if len(p) else None
                    if c is None:
                        continue
                    if p.get("name") == "text" and c.tag == "string":
                        self.retr.append(f"{ref}.setItemText({i}, {self.tr(c)})")
                    elif p.get("name") == "icon":
                        pre, expr = self.value(c, ref)
                        self.setup += pre
                        self.setup.append(f"{ref}.setItemIcon({i}, {expr})")
        elif cls == "QListWidget":
            for i, it in enumerate(el.findall("item")):
                self.setup.append(f"item = QtWidgets.QListWidgetItem({ref})")
                self.item_props(it, "item", f"{ref}.item({i})")
        elif cls == "QTableWidget":
            cols, rows = el.findall("column"), el.findall("row")
            self.setup += [f"{ref}.setColumnCount({len(cols)})", f"{ref}.setRowCount({len(rows)})"]
            for i, it in enumerate(cols):
                self.setup += ["item = QtWidgets.QTableWidgetItem()", f"{ref}.setHorizontalHeaderItem({i}, item)"]
                self.item_props(it, "item", f"{ref}.horizontalHeaderItem({i})")
            for i, it in enumerate(rows):
                self.setup += ["item = QtWidgets.QTableWidgetItem()", f"{ref}.setVerticalHeaderItem({i}, item)"]
                self.item_props(it, "item", f"{ref}.verticalHeaderItem({i})")
            for it in el.findall("item"):
                r, c = it.get("row", "0"), it.get("column", "0")
                self.setup += ["item = QtWidgets.QTableWidgetItem()", f"{ref}.setItem({r}, {c}, item)"]
                self.item_props(it, "item", f"{ref}.item({r}, {c})")
        elif cls == "QTreeWidget":
            cols = el.findall("column")
            if cols:
                self.setup.append(f"{ref}.setColumnCount({len(cols)})")
            for i, it in enumerate(cols):
                for p in it.findall("property"):
                    c = p[0] if len(p) else None
                    if p.get("name") == "text" and c is not None and c.tag == "string":
                        self.retr.append(f"{ref}.headerItem().setText({i}, {self.tr(c)})")
            self.tree_items(el, ref, ref, 0)

    def widget(self, el, parent_ref, parent_cls, top: bool = False) -> None:
        cls, name = el.get("class", "QWidget"), el.get("name") or "widget"
        ref = self.root_name if top else "self." + _ident(name)
        self.widgets += 1
        if not top:
            arg = "" if parent_cls in _PAGE_PARENTS else f"parent={parent_ref}"
            self.setup.append(f"{ref} = {self.qual(cls)}({arg})")
        self.setup.append(f"{ref}.setObjectName({_q(name)})")

        late = self.props(el, ref, cls, top)
        self.attrs(el, ref, parent_ref, parent_cls)
        self.items(el, ref, cls)

        for ch in el:
            if ch.tag == "layout":
                self.layout(ch, ref, cls, None)
            elif ch.tag == "widget":
                self.widget(ch, ref, cls)
            elif ch.tag == "addaction":
                self.addaction(ch, ref, cls)
        for p in late:
            self.do_prop(p, ref, top)
        if not top:
            self.attach(el, cls, name, ref, parent_ref, parent_cls)

    def addaction(self, ch, ref: str, cls: str) -> None:
        n = ch.get("name") or ""
        if n == "separator":
            self.deferred.append(f"{ref}.addSeparator()")
        elif n in self.menu_names:
            self.deferred.append(f"{ref}.addAction({self.ref(n)}.menuAction())")
        elif n in self.widget_names and cls in ("QToolBar", "QStatusBar"):
            self.deferred.append(f"{ref}.addWidget({self.ref(n)})")
        else:
            self.deferred.append(f"{ref}.addAction({self.ref(n)})")

    def attach(self, el, cls, name, ref, parent_ref, parent_cls) -> None:
        out = self.setup
        area = None
        for a in el.findall("attribute"):
            if a.get("name") in ("toolBarArea", "dockWidgetArea") and len(a):
                area = a[0]
        if parent_cls == "QMainWindow":
            if cls == "QMenuBar":
                out.append(f"{parent_ref}.setMenuBar({ref})")
            elif cls == "QStatusBar":
                out.append(f"{parent_ref}.setStatusBar({ref})")
            elif cls == "QToolBar":
                v = _txt(area, "TopToolBarArea")
                v = f"QtCore.Qt.ToolBarArea({v})" if v.isdigit() else self.enum("Qt::" + v)
                out.append(f"{parent_ref}.addToolBar({v}, {ref})")
                brk = next((a for a in el.findall("attribute") if a.get("name") == "toolBarBreak"), None)
                if brk is not None and _txt(brk.find("bool")) == "true":
                    out.append(f"{parent_ref}.insertToolBarBreak({ref})")
            elif cls == "QDockWidget":
                v = _txt(area, "2")
                v = f"QtCore.Qt.DockWidgetArea({v})" if v.isdigit() else self.enum("Qt::" + v)
                out.append(f"{parent_ref}.addDockWidget({v}, {ref})")
            else:
                out.append(f"{parent_ref}.setCentralWidget({ref})")
        elif parent_cls == "QTabWidget":
            out.append(f'{parent_ref}.addTab({ref}, "")')
        elif parent_cls == "QToolBox":
            out.append(f'{parent_ref}.addItem({ref}, "")')
        elif parent_cls == "QStackedWidget":
            out.append(f"{parent_ref}.addWidget({ref})")
        elif parent_cls == "QScrollArea":
            out.append(f"{parent_ref}.setWidget({ref})")
        elif parent_cls == "QDockWidget":
            out.append(f"{parent_ref}.setWidget({ref})")
        elif parent_cls in ("QMenuBar", "QMenu") and cls == "QMenu" and name not in self.referenced:
            out.append(f"{parent_ref}.addAction({ref}.menuAction())")
        elif parent_cls in ("QToolBar", "QStatusBar") and name not in self.referenced:
            out.append(f"{parent_ref}.addWidget({ref})")

    def layout(self, el, owner_ref: str, owner_cls: str, parent_lref,
               parent_lcls=None, item=None) -> None:
        cls, name = el.get("class", "QVBoxLayout"), el.get("name") or "layout"
        lref = "self." + _ident(name)
        arg = owner_ref if parent_lref is None else ""
        self.setup += [f"{lref} = {self.qual(cls)}({arg})", f"{lref}.setObjectName({_q(name)})"]

        margins = {}
        for p in el.findall("property"):
            pn, c = p.get("name") or "", (p[0] if len(p) else None)
            if c is None:
                continue
            if pn in _LAYOUT_MARGINS:
                margins[pn] = _txt(c)
            else:
                self.do_prop(p, lref, False)
        if margins:
            vals = ", ".join(margins.get(k, "-1") for k in _LAYOUT_MARGINS)
            self.setup.append(f"{lref}.setContentsMargins({vals})")
        for attr, fn in (("stretch", "setStretch"), ("rowstretch", "setRowStretch"),
                         ("columnstretch", "setColumnStretch"), ("rowminimumheight", "setRowMinimumHeight"),
                         ("columnminimumwidth", "setColumnMinimumWidth")):
            if el.get(attr):
                for i, v in enumerate(el.get(attr).split(",")):
                    if v.strip():
                        self.setup.append(f"{lref}.{fn}({i}, {v.strip()})")

        for it in el.findall("item"):
            child = next(iter(it), None)
            if child is None:
                continue
            if child.tag == "widget":
                self.widget(child, owner_ref, owner_cls)
                self.add_item(lref, cls, it, "widget", "self." + _ident(child.get("name") or "widget"))
            elif child.tag == "layout":
                self.layout(child, owner_ref, owner_cls, lref, cls, it)
            elif child.tag == "spacer":
                var = "spacerItem" + (str(self.spacers) if self.spacers else "")
                self.spacers += 1
                self.spacer(child, var)
                self.add_item(lref, cls, it, "spacer", var)

        if parent_lref is not None and item is not None:
            self.add_item(parent_lref, parent_lcls or "", item, "layout", lref)

    def spacer(self, el, var: str) -> None:
        props = {p.get("name"): (p[0] if len(p) else None) for p in el.findall("property")}
        horiz = _txt(props.get("orientation")) != "Qt::Vertical"
        size = props.get("sizeHint")
        w, h = (_txt(size.find("width"), "20"), _txt(size.find("height"), "20")) if size is not None else ("20", "20")
        st = self.enum(_txt(props.get("sizeType"), "QSizePolicy::Expanding"))
        mn = self.enum("QSizePolicy::Minimum")
        pol = f"{st}, {mn}" if horiz else f"{mn}, {st}"
        self.setup.append(f"{var} = QtWidgets.QSpacerItem({w}, {h}, {pol})")

    def add_item(self, lref: str, lcls: str, it, kind: str, ref: str) -> None:
        row, col = it.get("row"), it.get("column")
        rs, cs = it.get("rowspan", "1"), it.get("colspan", "1")
        al = self.flags(it.get("alignment")) if it.get("alignment") else None
        meth = {"widget": "addWidget", "layout": "addLayout", "spacer": "addItem"}[kind]
        if lcls == "QGridLayout":
            args = f"{ref}, {row or 0}, {col or 0}, {rs}, {cs}" + (f", {al}" if al else "")
        elif lcls == "QFormLayout":
            role = "SpanningRole" if cs == "2" else ("LabelRole" if col == "0" else "FieldRole")
            meth = {"widget": "setWidget", "layout": "setLayout", "spacer": "setItem"}[kind]
            args = f"{row or 0}, QtWidgets.QFormLayout.ItemRole.{role}, {ref}"
        else:
            args = ref
            if al and kind == "widget":
                args = f"{ref}, 0, {al}"
        self.setup.append(f"{lref}.{meth}({args})")

    def action(self, a) -> None:
        name = a.get("name") or "action"
        ref = "self." + _ident(name)
        self.setup += [f"{ref} = QtGui.QAction(parent={self.root_name})", f"{ref}.setObjectName({_q(name)})"]
        self.props(a, ref, "QAction")

    def run(self) -> Result:
        root = self.root
        top = root.find("widget")
        if top is None:
            raise ConversionError("Nenhum <widget> encontrado: o arquivo não parece ser um .ui do Qt Designer.")
        self.top_raw = top.get("name") or "Form"
        self.root_name = _ident(self.top_raw)
        base = top.get("class", "QWidget")
        ui_class = _txt(root.find("class")) or self.top_raw
        self.ctx = self.top_raw
        class_name = "Ui_" + _ident(ui_class)

        for cw in root.findall("customwidgets/customwidget"):
            cname, header = _txt(cw.find("class")), _txt(cw.find("header"))
            if cname:
                mod = re.sub(r"\.h(pp)?$", "", header).replace("/", ".") if header else cname.lower()
                self.custom[cname] = mod

        self.menu_names = {w.get("name") for w in root.iter("widget") if w.get("class") == "QMenu"}
        self.widget_names = {w.get("name") for w in root.iter("widget")}
        self.referenced = {a.get("name") for a in root.iter("addaction")}

        self.widget(top, None, None, top=True)

        for g in root.findall("buttongroups/buttongroup"):
            gname = g.get("name") or "buttonGroup"
            self.groups += [f"self.{_ident(gname)} = QtWidgets.QButtonGroup({self.root_name})",
                            f"self.{_ident(gname)}.setObjectName({_q(gname)})"]
        for a in root.iter("action"):
            self.action(a)
        if next(root.iter("actiongroup"), None) is not None:
            self.warn("<actiongroup> não é suportado; as ações foram criadas sem agrupamento.")

        conns = []
        for c in root.findall("connections/connection"):
            s, sig, r, sl = (_txt(c.find(k)) for k in ("sender", "signal", "receiver", "slot"))
            if s and sig and r and sl:
                conns.append(f"{self.ref(s)}.{sig.split('(')[0]}.connect({self.ref(r)}.{sl.split('(')[0]})")
        tabs = [_txt(t) for t in root.findall("tabstops/tabstop")]
        order = [f"{self.root_name}.setTabOrder({self.ref(a)}, {self.ref(b)})" for a, b in zip(tabs, tabs[1:])]

        trailer = []
        for inc in root.findall("resources/include"):
            loc = inc.get("location", "")
            if loc:
                trailer.append(f"# import {re.sub(r'[^0-9A-Za-z_]', '_', loc.rsplit('.', 1)[0].split('/')[-1])}_rc")
                self.warn("O .ui usa recursos (.qrc). O PyQt6 não tem pyrcc: compile o .qrc com outra "
                          "ferramenta e descomente o import no final do arquivo.")
        for cname, mod in self.custom.items():
            trailer.append(f"from {mod} import {cname}")

        rn = self.root_name
        body = (self.setup + self.groups + self.deferred + [f"self.retranslateUi({rn})"] + conns
                + [f"QtCore.QMetaObject.connectSlotsByName({rn})"] + order)
        ind = " " * 8
        modules = ["QtCore", "QtGui", "QtWidgets"] + sorted(self.extra_modules)

        out = [
            f"# Form implementation generated from reading ui file '{self.filename}'",
            "#",
            "# Gerado por UI2Py6 (conversor .ui -> PyQt6).",
            "# ATENÇÃO: alterações feitas neste arquivo serão perdidas se o .ui for convertido de novo.",
            "",
            f"from PyQt6 import {', '.join(modules)}",
            "",
            "",
            f"class {class_name}(object):",
            f"    def setupUi(self, {rn}):",
            *[ind + ln if ln else "" for ln in body],
            "",
            f"    def retranslateUi(self, {rn}):",
            f"{ind}_translate = QtCore.QCoreApplication.translate",
            *[ind + ln for ln in self.retr],
        ]
        if trailer:
            out += ["", ""] + trailer
        if self.executable:
            out += ["", "", 'if __name__ == "__main__":', "    import sys",
                    "    app = QtWidgets.QApplication(sys.argv)",
                    f"    {rn} = {self.qual(base)}()",
                    f"    ui = {class_name}()", f"    ui.setupUi({rn})",
                    f"    {rn}.show()", "    sys.exit(app.exec())"]
        return Result("\n".join(out) + "\n", class_name, base, self.widgets, self.warnings)


def converter_ui(source, filename: str = "formulario.ui", executable: bool = False) -> Result:
    """Converte o conteúdo de um .ui (str ou bytes) em código Python/PyQt6."""
    raw = source.encode("utf-8") if isinstance(source, str) else source
    head = raw.lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ConversionError("Arquivos .ui com DOCTYPE/ENTITY não são aceitos por segurança.")
    if isinstance(source, str):
        source = source.lstrip("\ufeff")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ConversionError(f"XML inválido: {exc}") from exc
    except ValueError as exc:
        raise ConversionError(f"Não foi possível ler o conteúdo: {exc}") from exc
    if root.tag != "ui":
        raise ConversionError("O arquivo não parece ser um .ui do Qt Designer (tag raiz <ui> não encontrada).")
    return _Converter(root, filename, executable).run()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
