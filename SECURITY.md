# Segurança do SPPtab

O aplicativo para Windows inicia um servidor PHP em `127.0.0.1` e expõe apenas as páginas e os recursos estáticos permitidos pelo roteador. A API exige POST com JSON, token da sessão, origem local e tamanho limitado. Caminhos de arquivos são resolvidos dentro da biblioteca local antes de leitura, conversão ou remoção.

As transferências HTTPS verificam o domínio oficial, impõem limites de tamanho e validam o arquivo DBC antes de guardá-lo. O FTP do DATASUS é uma alternativa quando o HTTPS falha; por não ser criptografado, pode ser desativado com `TABWIN2_ALLOW_FTP_FALLBACK=0`. Quando desativado, arquivos já presentes na biblioteca continuam disponíveis.

O atualizador baixa a versão do repositório oficial, confere o SHA-256 publicado com o pacote, limita a extração e mantém uma cópia para recuperação em caso de falha. O checksum detecta corrupção ou troca do arquivo durante a transferência, mas não substitui uma assinatura digital independente. O executável ainda não é assinado digitalmente.

Para comunicar uma falha de segurança, envie os detalhes para lisandrowork1@gmail.com. Evite publicar dados locais ou informações de pacientes em uma issue pública.
