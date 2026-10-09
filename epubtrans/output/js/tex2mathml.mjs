// LaTeX → MathML（EPUB 用）。stdin：[{tex, display}]；stdout：[MathML 或 null]（轉不了的回 null）。
// annotate：MathML 裡附上 TeX 原文（application/x-tex），PDF 端讀譯本 EPUB 時靠它取回 LaTeX 交給 Typst。
import temml from "temml";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(({ tex, display }) => {
  try {
    return temml.renderToString(tex, { displayMode: !!display, annotate: true, xml: true, throwOnError: true });
  } catch (e) {
    return null;
  }
});
process.stdout.write(JSON.stringify(out));
