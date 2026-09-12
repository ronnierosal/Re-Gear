import ts from "typescript";

export function runtimeDependencies(text, forbiddenModule=/backend|@decky\/api/, forbiddenIdentifier=/^(getSnapshot|invoke|fetch|localStorage|sessionStorage)$/) {
  const tree=ts.createSourceFile('detail-ui.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const found=[];
  const forbiddenCall=/^(getSnapshot|invoke|fetch)$/;
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier
        && ts.isStringLiteral(node.moduleSpecifier) && forbiddenModule.test(node.moduleSpecifier.text)) {
      found.push(node.moduleSpecifier.text);
    }
    if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)
        && node.moduleReference.expression && ts.isStringLiteral(node.moduleReference.expression)
        && forbiddenModule.test(node.moduleReference.expression.text)) found.push(node.moduleReference.expression.text);
    if (ts.isIdentifier(node) && forbiddenIdentifier.test(node.text)) found.push(node.text);
    if (ts.isCallExpression(node)) {
      const target=node.expression;
      const name=ts.isIdentifier(target) ? target.text
        : ts.isPropertyAccessExpression(target) ? target.name.text
        : ts.isElementAccessExpression(target) && target.argumentExpression && ts.isStringLiteral(target.argumentExpression)
          ? target.argumentExpression.text : '';
      if (forbiddenCall.test(name)) found.push(name);
      if ((target.kind===ts.SyntaxKind.ImportKeyword || name==='require')
          && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
          && forbiddenModule.test(node.arguments[0].text)) found.push(node.arguments[0].text);
    }
    ts.forEachChild(node,visit);
  }
  visit(tree);
  return found;
}


export function executableSource(text) {
  const tree=ts.createSourceFile("presentation.tsx",text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  return ts.createPrinter({removeComments:true}).printFile(tree);
}
