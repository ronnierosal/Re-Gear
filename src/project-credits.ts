import {noticesText,licenseText} from 'regear:project-documents';

export const noticesUrl='https://github.com/ronnierosal/Re-Gear/blob/main/THIRD_PARTY_NOTICES.md';
export const licenseUrl='https://github.com/ronnierosal/Re-Gear/blob/main/LICENSE';

/** Preserve source wording rather than maintain a second attribution list.
 * Render as text, never HTML: document markup is not executable UI. */
export function parseProjectDocuments(notices:string,license:string){
 const sections:Array<{title:string;body:string}>=[];
 for(const line of notices.replace(/\r\n/g,'\n').split('\n')){
  const heading=/^#{1,2} (.+)$/.exec(line);
  if(heading)sections.push({title:heading[1],body:''});
  else if(sections.length)sections[sections.length-1].body+=line+'\n';
 }
 return {
  sections:sections.map(section=>({...section,body:section.body.trim()})),
  copyright:license.split(/\r?\n/).find(line=>/^Copyright\b/.test(line))??'',
  licenseId:/^SPDX-License-Identifier:\s*(.+)$/m.exec(license)?.[1]?.trim()??'',
  licenseText:license,
 };
}
export const projectDocuments=parseProjectDocuments(noticesText,licenseText);
