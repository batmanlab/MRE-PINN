import numpy as np
import torch
import deepxde

jacobian = deepxde.grad.jacobian
hessian = deepxde.grad.hessian


def laplacian(u, x, dim=0):
    '''
    Continuous Laplacian operator.

    Args:
        u: (N, M) output tensor.
        x: (N, K) input tensor.
        dim: Summation start index.
    Returns:
        v: (N, M) Laplacian tensor.
    '''
    components = []
    for i in range(u.shape[1]):
        c = i if u.shape[1] > 1 else None
        component = 0
        for j in range(dim, x.shape[1]):
            component += hessian(u, x, component=c, i=j, j=j)
        components.append(component)
    return torch.cat(components, dim=1)


class WaveEquation(object):
    '''
    Navier-Cauchy equation for steady-state
    elastic wave vibration.

    ∇·[μ(∇u + (∇u)ᵀ) + λ(∇·u)I] = -ρω²u
    '''
    def __init__(
        self, detach, rho=1000, debug=False
    ):
        self.detach = detach
        self.rho = rho
        self.homogeneous = True
        self.incompressible = True
        self.debug = debug

    def __call__(self, x, outputs):
        '''
        Args:
            x: (N x 4) input tensor of omega,x,y,z
            outputs: (N x 4) tensor of ux,uy,uz,mu
        Returns:
            (N x 3) tensor of PDE residual for each
                ux,uy,uz displacement component
        '''
        u, mu = outputs[:,:-1], outputs[:,-1:]
        omega = x[:,:1]

        laplace_u = laplacian(u, x, dim=1)
        if self.detach: # only backprop to mu
            u, laplace_u = u.detach(), laplace_u.detach()

        # Helmholtz equation
        div_stress = mu * laplace_u
        f = self.rho * (2 * np.pi * omega)**2 * u

        return div_stress + f


def lvwe(x, u, mu, lam, rho, omega):
    '''
    General form of the steady-state
    linear viscoelastic wave equation.
    '''
    jac_u = jacobian(u, x)

    strain = (1/2) * (jac_u + jac_u.T)
    stress = 2 * mu * strain + lam * trace(strain) * I

    lhs = divergence(stress, x)

    return lhs + rho * omega**2 * u


def homogeneous_lvwe(x, u, mu, lam, rho, omega):
    '''
    Linear viscoelastic wave equation
    with assumption of homogeneity.
    '''
    laplace_u = laplacian(u, x)
    div_u = divergence(u, x)
    grad_div_u = gradient(div_u, x)

    lhs = mu * laplace_u + (lam + mu) * grad_div_u

    return lhs + rho * omega**2 * u


def incompressible_homogeneous_lvwe(x, u, mu, rho, omega):
    '''
    Linear viscoelastic wave equation
    with assumption of homogeneity and
    incompressibility.
    '''
    laplace_u = laplacian(u, x)

    lhs = mu * laplace_u

    return lhs + rho * omega**2 * u


def pressure_homogeneous_lvwe(x, u, mu, p, rho, omega):
    '''
    Linear viscoelastic wave equation
    with assumption of homogeneity and
    additional pressure term.
    '''
    laplace_u = laplacian(u, x)
    grad_p = gradient(p, x)

    lhs = mu * laplace_u + grad_p

    return lhs + rho * omega**2 * u
