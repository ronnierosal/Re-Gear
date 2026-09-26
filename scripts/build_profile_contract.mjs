/** Build-time profile selection. No browser setting can switch this policy. */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

export function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key=>`${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export function resolveBuildProfile(profile = 'development', contract = JSON.parse(readFileSync(new URL('../contracts/build-profiles.json', import.meta.url),'utf8'))) {
  const expected={schema_version:1,profiles:{development:{feature_policy:'existing_development_surface',enabled_features:['*']},production:{feature_policy:'stable_allowlist',enabled_features:['egpu_connection','safe_disconnect','brightness','volume']}}};
  if(canonicalJson(contract)!==canonicalJson(expected))throw new Error('release.profile_contract_invalid');
  if(profile!=='development'&&profile!=='production')throw new Error('release.profile_unknown');
  return {schema_version:1,profile,feature_policy:contract.profiles[profile].feature_policy,
    enabled_features:contract.profiles[profile].enabled_features,
    contract_sha256:createHash('sha256').update(canonicalJson(contract)).digest('hex')};
}

export function buildProfilePlugin(profile = process.env.REGEAR_BUILD_PROFILE ?? 'development') {
  const metadata=resolveBuildProfile(profile);
  return {
    name:'regear-build-profile',
    resolveId(source){return source==='regear:build-profile'?'\0regear:build-profile':null;},
    load(id){return id==='\0regear:build-profile'?`export const buildProfile=${JSON.stringify(metadata.profile)};`:null;},
    generateBundle(_options,bundle){
      const entry=Object.values(bundle).find(output=>output.type==='chunk'&&output.isEntry);
      if(!entry)throw new Error('release.frontend_entry_missing');
      this.emitFile({type:'asset',fileName:'build_profile.json',source:JSON.stringify({...metadata,
        bundle_sha256:createHash('sha256').update(entry.code).digest('hex')})+'\n'});
    },
  };
}
