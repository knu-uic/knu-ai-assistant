// Official relocatable Node distribution, not the build machine's Homebrew binary.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { copyPortableNode } from './runtime-layout.mjs';

const version='22.23.1';
const checksums={
  'darwin-arm64':'ef28d8fab2c0e4314522d4bb1b7173270aa3937e93b92cb7de79c112ac1fa953',
  'darwin-x64':'b8da981b8a0b1241b70249204916da76c63573ddf5814dbd2d1e41069105cb81',
  'linux-arm64':'543fa39e57d4c07855939459a323f4deb9a79dd1bb45e6e99458b0f2de10db8d',
  'linux-x64':'7a8cb04b4a1df4eaf432125324b81b29a088e73570a23259a8de1c65d07fc129',
};
const target=`${process.platform}-${process.arch}`;
if(!checksums[target]) throw new Error(`Provide a matching KNU_NODE_RUNTIME manually for ${target}`);
if(!process.argv[2]) throw new Error('Pass a new destination directory');
const destination=path.resolve(process.argv[2]);
try { await fs.access(destination); throw new Error('Node destination already exists'); }
catch(e) { if(e.code!=='ENOENT') throw e; }
const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'knu-context-node-'));
try {
  const name=`node-v${version}-${target}`;
  const response=await fetch(`https://nodejs.org/dist/v${version}/${name}.tar.gz`,{signal:AbortSignal.timeout(120000)});
  if(!response.ok) throw new Error(`Node download failed: ${response.status}`);
  const bytes=Buffer.from(await response.arrayBuffer());
  if(createHash('sha256').update(bytes).digest('hex')!==checksums[target]) throw new Error('Node SHA256 mismatch');
  const archive=path.join(temporary,'node.tar.gz');
  await fs.writeFile(archive,bytes);
  await new Promise((resolve,reject)=>{
    const child=spawn('tar',['-xzf',archive,'-C',temporary],{stdio:'inherit'});
    child.on('error',reject); child.on('exit',code=>code===0?resolve():reject(new Error('Node extraction failed')));
  });
  await copyPortableNode(path.join(temporary,name),destination);
  console.log(`KNU_NODE_RUNTIME=${destination}`);
} finally { await fs.rm(temporary,{recursive:true,force:true}); }
