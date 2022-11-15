import time
import numpy as np
import xarray as xr
import torch
import deepxde

from ..utils import as_xarray
from ..pde import laplacian
from .. import discrete
from .losses import msae_loss


class PINOData(deepxde.data.Data):

    def __init__(self, cohort, pde, patch_size=None, batch_size=None, device='cuda'):
        self.cohort = cohort
        self.pde = pde
        self.mask_level = 1.0

        self.batch_sampler = deepxde.data.BatchSampler(len(cohort), shuffle=True)
        self.batch_size = batch_size
        self.patch_size = patch_size
        self.device = device

    def losses(self, targets, outputs, loss_fn, inputs, model, aux=None):
        a, x = inputs
        u_true, mu_true, mask = torch.split(targets, 1, dim=-1)
        u_pred, mu_pred = outputs[:2]
        u_loss = loss_fn(u_true, u_pred, mask, self.mask_level)
        mu_loss = loss_fn(mu_true, mu_pred, mask, self.mask_level)
        pde_res = self.pde(x, u_pred, mu_pred)
        pde_loss = loss_fn(0, pde_res, mask, self.mask_level)
        return [u_loss, mu_loss, pde_loss]

    def get_tensors(self, idx, patch_size=None):
        '''
        Args:
            idx: Patient index in cohort.
        Returns:
            input: Tuple of input tensors.
            target: Target tensor.
            aux_vars: Tuple of auxiliary tensors.
        '''
        patient = self.cohort[idx]
        a_sequences = [
            't1_pre_in', 't1_pre_out', 't1_pre_water', 't1_pre_fat'
        ]
        a_arrays = [patient.arrays[seq].values for seq in a_sequences]
        a = np.stack(a_arrays, axis=-1)
        x = patient.arrays['wave'].field.points(reshape=False) * 1e-3
        u = patient.arrays['wave'].values[...,None]
        mu = patient.arrays['mre'].values[...,None]
        mask = patient.arrays['mre_mask'].values[...,None]

        if patch_size is not None: # sample patch
            n_x, n_y, n_z = y.shape[:3]
            patch_x = np.random.randint(n_x - patch_size + 1)
            patch_y = np.random.randint(n_y - patch_size + 1)

            a = a[patch_x:patch_x + patch_size, patch_y:patch_y + patch_size]
            x = x[patch_x:patch_x + patch_size, patch_y:patch_y + patch_size]
            u = u[patch_x:patch_x + patch_size, patch_y:patch_y + patch_size]
            mu = mu[patch_x:patch_x + patch_size, patch_y:patch_y + patch_size]
            mask = mask[patch_x:patch_x + patch_size, patch_y:patch_y + patch_size]

        # convert arrays to tensors
        a = torch.tensor(a, device=self.device, dtype=torch.float32)
        x = torch.tensor(x, device=self.device, dtype=torch.float32)
        u = torch.tensor(u, device=self.device, dtype=torch.float32)
        mu = torch.tensor(mu, device=self.device, dtype=torch.float32)
        mask = torch.tensor(mask, device=self.device, dtype=torch.float32)

        return (u, x), torch.cat([u, mu, mask], dim=-1), ()

    def train_next_batch(self, batch_size=None, return_inds=False):
        '''
        Args:
            batch_size: Number of patients in batch.
        Returns:
            inputs: Tuple of input tensors.
            targets: Tuple of target tensors.
            aux_vars: Tuple of auxiliary tensors.
        '''
        t_start = time.time()

        batch_size = batch_size or self.batch_size
        batch_inds = self.batch_sampler.get_next(batch_size)

        inputs, targets, aux_vars = [], [], []
        for idx in batch_inds:
            input, target, aux = self.get_tensors(idx, self.patch_size)
            inputs.append(input)
            targets.append(target)
            aux_vars.append(aux)

        inputs = tuple(torch.stack(x) for x in zip(*inputs))
        targets = torch.stack(targets)
        aux_vars = tuple(torch.stack(x) for x in zip(*aux_vars))
        
        if return_inds:
            return inputs, targets, aux_vars, batch_inds
        else:
            return inputs, targets, aux_vars

    def test(self, return_inds=False):
        return self.train_next_batch(batch_size=1, return_inds=return_inds)


class PINOModel(deepxde.Model):
    
    def __init__(self, data, net, pde, patch_size=None, batch_size=None):

        # initialize the training data
        data = PINOData(data, pde, patch_size, batch_size)

        # initialize the network weights
        #TODO net.init_weights()

        super().__init__(data, net)

    def predict(self, a, x):
        x.requires_grad = True
        u_pred, mu_pred = self.net.forward(inputs=(a, x), debug=True)
        lu_pred = laplacian(u_pred, x)
        f_trac, f_body = self.data.pde.traction_and_body_forces(x, u_pred, mu_pred)
        return u_pred, mu_pred, lu_pred, f_trac, f_body

    def benchmark(self, n_iters=100):

        print(f'# iterations: {n_iters}')
        data_time = 0
        model_time = 0
        loss_time = 0
        for i in range(n_iters):
            t_start = time.time()
            inputs, targets, aux_vars = self.data.train_next_batch()
            t_data = time.time()
            u, x = inputs
            x.requires_grad = True
            outputs = self.net(inputs)
            t_model = time.time()
            losses = self.data.losses(targets, outputs, msae_loss, inputs, self)
            t_loss = time.time()
            data_time += (t_data - t_start) / n_iters
            model_time += (t_model - t_data) / n_iters
            loss_time += (t_loss - t_model) / n_iters

        iter_time = data_time + model_time + loss_time
        print(f'Data time/iter:  {data_time:.4f}s ({data_time/iter_time*100:.2f}%)')
        print(f'Model time/iter: {model_time:.4f}s ({model_time/iter_time*100:.2f}%)')
        print(f'Loss time/iter:  {loss_time:.4f}s ({loss_time/iter_time*100:.2f}%)')
        print(F'Total time/iter: {iter_time:.4f}s')

        total_time = iter_time * n_iters
        print(f'Total time: {total_time:.4f}s')
        print(f'1k iters time: {iter_time * 1e3 / 60:.2f}m')
        print(f'10k iters time: {iter_time * 1e4 / 60:.2f}m')
        print(f'100k iters time: {iter_time * 1e5 / 3600:.2f}h')

    def test(self):
        
        # get model predictions as tensors
        inputs, targets, aux_vars, inds = self.data.test(return_inds=True)
        u_pred, mu_pred, lu_pred, f_trac, f_body = self.predict(*inputs)
        Mu_pred = -1000 * (2 * np.pi * 80)**2 * u_pred / lu_pred
        mu_pred *= 100 # scale hack?

        # get ground truth xarrays
        a_mask = self.data.cohort[inds[0]].arrays['anat_mask']
        m_mask = self.data.cohort[inds[0]].arrays['mre_mask']
        a_true = self.data.cohort[inds[0]].arrays['t1_pre_in']
        u_true = self.data.cohort[inds[0]].arrays['wave']
        Lu_true = self.data.cohort[inds[0]].arrays['Lwave']
        Mu_true = self.data.cohort[inds[0]].arrays['Mwave']
        mu_true = self.data.cohort[inds[0]].arrays['mre']

        # apply mask level
        mask_level = 1.0
        a_mask = (a_mask - 1) * mask_level + 1
        m_mask = (m_mask - 1) * mask_level + 1

        # convert predicted tensors to xarrays
        u_pred  = as_xarray(u_pred[0,...,0], like=u_true)
        lu_pred = as_xarray(lu_pred[0,...,0], like=u_true)
        f_trac  = as_xarray(f_trac[0,...,0], like=u_true)
        f_body  = as_xarray(f_body[0,...,0], like=u_true)
        Mu_pred = as_xarray(Mu_pred[0,...,0], like=Mu_true)
        mu_pred = as_xarray(mu_pred[0,...,0], like=mu_true)
        
        # combine xarrays into single xarray

        if True:
            a_vars = ['a_mask', 'a_over', 'a_true']
            a_dim = xr.DataArray(a_vars, dims=['variable'])
            a = xr.concat([a_mask, a_mask * a_true, a_true], dim=a_dim)
            a.name = 'anatomy'

        if True:
            u_vars = ['u_pred', 'u_diff', 'u_true']
            u_dim = xr.DataArray(u_vars, dims=['variable'])
            u = xr.concat(
                [u_pred * m_mask, (u_true - u_pred) * m_mask, u_true * m_mask],
                dim=u_dim
            )
            u.name = 'wave field'

        if True:
            lu_vars = ['lu_pred', 'lu_diff', 'Lu_true']
            lu_dim = xr.DataArray(lu_vars, dims=['variable'])
            lu = xr.concat(
                [lu_pred * m_mask, (Lu_true - lu_pred) * m_mask, Lu_true * m_mask],
                dim=lu_dim
            )
            lu.name = 'Laplacian'

        if True:
            pde_vars = ['f_trac', 'pde_diff', 'pde_grad']
            pde_dim = xr.DataArray(pde_vars, dims=['variable'])
            pde = xr.concat(
                [f_trac * m_mask, (f_trac + f_body) * m_mask, 2 * lu_pred * (f_trac + f_body) * m_mask],
                dim=pde_dim
            )
            pde.name = 'PDE'

        if True:
            mu_vars = ['mu_pred', 'mu_diff', 'mu_true']
            mu_dim = xr.DataArray(mu_vars, dims=['variable'])
            mu = xr.concat(
                [mu_pred * m_mask, (mu_true - mu_pred) * m_mask, mu_true * m_mask],
                dim=mu_dim
            )
            mu.name = 'elastogram'

        if True:
            Mu_vars = ['Mu_pred', 'Mu_diff', 'Mu_true']
            Mu_dim = xr.DataArray(Mu_vars, dims=['variable'])
            Mu = xr.concat(
                [Mu_pred * m_mask, (Mu_true - Mu_pred) * m_mask, Mu_true * m_mask],
                dim=Mu_dim
            )
            Mu.name = 'baseline'

        return u, lu, pde, mu, Mu
